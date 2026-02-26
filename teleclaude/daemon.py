"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import hashlib
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Coroutine, Literal, Optional, TextIO, cast

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude.channels.worker import run_subscription_worker
from teleclaude.config import config, config_path  # config.py loads .env at import time
from teleclaude.config.loader import load_project_config
from teleclaude.config.runtime_settings import RuntimeSettings
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.agents import AgentName
from teleclaude.core.cache import DaemonCache
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.command_registry import init_command_service
from teleclaude.core.command_service import CommandService
from teleclaude.core.db import HookOutboxRow, db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    DeployArgs,
    ErrorEventContext,
    EventType,
    SessionLifecycleContext,
    SystemCommandContext,
    TeleClaudeEvents,
    build_agent_payload,
    parse_command_string,
)
from teleclaude.core.lifecycle import DaemonLifecycle
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_utils import (
    get_output_file,
    get_short_project_name,
    resolve_working_dir,
    split_project_path_and_subdir,
)
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todo_watcher import TodoWatcher
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.hooks.api_routes import set_contract_registry
from teleclaude.hooks.bridge import EventBusBridge
from teleclaude.hooks.config import load_hooks_config
from teleclaude.hooks.delivery import WebhookDeliveryWorker
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.inbound import InboundEndpointRegistry, NormalizerRegistry
from teleclaude.hooks.normalizers import register_builtin_normalizers
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event
from teleclaude.logging_config import setup_logging
from teleclaude.notifications import NotificationOutboxWorker
from teleclaude.services.deploy_service import DeployService
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.services.maintenance_service import MaintenanceService
from teleclaude.services.monitoring_service import MonitoringService
from teleclaude.transport.redis_transport import RedisTransport
from teleclaude.tts.manager import TTSManager
from teleclaude.types.commands import ResumeAgentCommand, StartAgentCommand

init_voice_handler = voice_message_handler.init_voice_handler


@dataclass(frozen=True)
class OutputChangeSummary:
    """Summary details for tmux output changes."""

    changed: bool
    reason: str | None = None
    before_len: int | None = None
    after_len: int | None = None
    diff_index: int | None = None
    before_snippet: str | None = None
    after_snippet: str | None = None


@dataclass
class _HookOutboxQueueItem:
    """In-memory queue payload for per-session hook outbox processing."""

    row: HookOutboxRow
    event_type: str
    classification: Literal["critical", "bursty"]


@dataclass
class _HookOutboxSessionQueue:
    """Per-session hook queue state."""

    pending: list[_HookOutboxQueueItem] = field(default_factory=list)
    claimed_row_ids: set[int] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notify: asyncio.Event = field(default_factory=asyncio.Event)


# Logging defaults (can be overridden via environment variables)
DEFAULT_LOG_LEVEL = "INFO"

# Startup retry configuration
STARTUP_MAX_RETRIES = 3
STARTUP_RETRY_DELAYS = [10, 20, 40]  # Exponential backoff in seconds

# API server restart policy (centralized in lifecycle)
API_RESTART_MAX = int(os.getenv("API_RESTART_MAX", "5"))
API_RESTART_WINDOW_S = float(os.getenv("API_RESTART_WINDOW_S", "60"))
API_RESTART_BACKOFF_S = float(os.getenv("API_RESTART_BACKOFF_S", "1"))

# Resource monitoring
RESOURCE_SNAPSHOT_INTERVAL_S = float(os.getenv("RESOURCE_SNAPSHOT_INTERVAL_S", "60"))
LAUNCHD_WATCH_INTERVAL_S = float(os.getenv("LAUNCHD_WATCH_INTERVAL_S", "300"))
LAUNCHD_WATCH_ENABLED = os.getenv("TELECLAUDE_LAUNCHD_WATCH", "1") == "1"
CODEX_TRANSCRIPT_WATCH_INTERVAL_S = float(os.getenv("CODEX_TRANSCRIPT_WATCH_INTERVAL_S", "1"))

# Hook outbox worker
HOOK_OUTBOX_POLL_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_POLL_INTERVAL_S", "1"))
HOOK_OUTBOX_BATCH_SIZE: int = int(os.getenv("HOOK_OUTBOX_BATCH_SIZE", "25"))
HOOK_OUTBOX_LOCK_TTL_S: float = float(os.getenv("HOOK_OUTBOX_LOCK_TTL_S", "30"))
HOOK_OUTBOX_BASE_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_BASE_BACKOFF_S", "1"))
HOOK_OUTBOX_MAX_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_MAX_BACKOFF_S", "60"))
HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S: float = float(os.getenv("HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S", "5"))
HOOK_OUTBOX_SESSION_MAX_PENDING: int = int(os.getenv("HOOK_OUTBOX_SESSION_MAX_PENDING", "32"))
HOOK_OUTBOX_SUMMARY_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_SUMMARY_INTERVAL_S", "15"))
HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD: int = int(os.getenv("HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD", "20"))
HOOK_OUTBOX_LAG_WARN_THRESHOLD_S: float = float(os.getenv("HOOK_OUTBOX_LAG_WARN_THRESHOLD_S", "3"))
HOOK_OUTBOX_WARN_LOG_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_WARN_LOG_INTERVAL_S", "15"))
HOOK_OUTBOX_MAX_LAG_SAMPLES: int = int(os.getenv("HOOK_OUTBOX_MAX_LAG_SAMPLES", "2048"))

HOOK_EVENT_CLASS_CRITICAL: frozenset[str] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_SESSION_END,
        AgentHookEvents.AGENT_NOTIFICATION,
        AgentHookEvents.AGENT_ERROR,
    }
)
HOOK_EVENT_CLASS_BURSTY: frozenset[str] = frozenset(
    {
        AgentHookEvents.TOOL_USE,
        AgentHookEvents.TOOL_DONE,
    }
)

# Notification outbox worker
NOTIFICATION_OUTBOX_POLL_INTERVAL_S: float = float(os.getenv("NOTIFICATION_OUTBOX_POLL_INTERVAL_S", "1"))
NOTIFICATION_OUTBOX_BATCH_SIZE: int = int(os.getenv("NOTIFICATION_OUTBOX_BATCH_SIZE", "25"))
NOTIFICATION_OUTBOX_LOCK_TTL_S: float = float(os.getenv("NOTIFICATION_OUTBOX_LOCK_TTL_S", "30"))
NOTIFICATION_OUTBOX_BASE_BACKOFF_S: float = float(os.getenv("NOTIFICATION_OUTBOX_BASE_BACKOFF_S", "1"))
NOTIFICATION_OUTBOX_MAX_BACKOFF_S: float = float(os.getenv("NOTIFICATION_OUTBOX_MAX_BACKOFF_S", "60"))


# Agent auto-command startup detection
AGENT_START_TIMEOUT_S = 5.0
AGENT_START_POLL_INTERVAL_S = 0.5
AGENT_START_SETTLE_DELAY_S = 0.5  # Initial delay after process starts
AGENT_START_CONFIRM_ENTER_DELAY_S = 1.0
AGENT_START_CONFIRM_ENTER_ATTEMPTS = 4
AGENT_START_OUTPUT_POLL_INTERVAL_S = 0.2
AGENT_START_OUTPUT_CHANGE_TIMEOUT_S = 2.5
AGENT_START_ENTER_INTER_DELAY_S = 0.2
AGENT_START_POST_INJECT_DELAY_S = 1.0
AGENT_START_STABILIZE_TIMEOUT_S = 10.0  # Max wait for output to stop changing during startup
AGENT_START_STABILIZE_QUIET_S = 1.0  # How long output must be quiet to be "stable"
AGENT_START_POST_STABILIZE_DELAY_S = 0.5  # Safety buffer after stabilization
GEMINI_START_EXTRA_DELAY_S = float(os.getenv("GEMINI_START_EXTRA_DELAY_S", "3"))

logger = get_logger("teleclaude.daemon")


def _is_retryable_startup_error(error: Exception) -> bool:
    """Check if startup error is transient and worth retrying.

    Retryable errors include network issues like DNS failures, connection
    timeouts, and refused connections. Non-retryable errors include
    configuration errors, authentication failures, and lock errors.

    Args:
        error: The exception that occurred during startup

    Returns:
        True if the error is transient and startup should be retried
    """
    # Error type names that indicate transient network issues
    retryable_types = ("NetworkError", "ConnectError", "TimeoutError", "OSError")
    # Error message patterns that indicate transient issues
    retryable_messages = ("name resolution", "connection refused", "timed out", "temporary failure")

    error_type = type(error).__name__
    error_msg = str(error).lower()

    if error_type in retryable_types:
        return True
    if any(msg in error_msg for msg in retryable_messages):
        return True
    return False


class DaemonLockError(Exception):
    """Raised when another daemon instance is already running."""


class TeleClaudeDaemon:  # pylint: disable=too-many-instance-attributes  # Daemon coordinator needs multiple components
    """Main TeleClaude daemon that coordinates all components."""

    def __init__(self, env_path: str):
        """Initialize daemon.

        Args:
            env_path: Path to .env file
        """
        # Load environment variables
        load_dotenv(env_path)

        # Log experiment status if any are enabled
        if config.experiments:
            logger.info("Loaded %d experiments from overlay", len(config.experiments))
            for exp in config.experiments:
                logger.debug("Active experiment: name=%s agents=%s", exp.name, exp.agents)

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: Optional[TextIO] = None  # Will hold the locked file handle

        # Note: tmux_bridge and db are functional modules (no instantiation)
        # UI output management is now handled by UiAdapter (base class for Telegram, Slack, etc.)
        self.output_poller = OutputPoller()

        # Initialize task registry for tracking background tasks
        self.task_registry = TaskRegistry()

        # Initialize unified adapter client (observer pattern - NO daemon reference)
        self.client = AdapterClient(task_registry=self.task_registry)
        self.command_service = init_command_service(
            CommandService(
                client=self.client,
                start_polling=self._start_polling_for_session,
                execute_terminal_command=self._execute_terminal_command,
                execute_auto_command=self._execute_auto_command,
                queue_background_task=self._queue_background_task,
                bootstrap_session=self._bootstrap_session_resources,
            )
        )

        # Initialize cache for remote data
        self.cache = DaemonCache()
        logger.info("DaemonCache initialized")

        # Initialize TTS manager for direct speech (no event bus coupling)
        self.tts_manager = TTSManager()
        logger.info("TTSManager initialized")

        # Mutable runtime settings with debounced YAML persistence
        self.runtime_settings = RuntimeSettings(config_path, self.tts_manager)

        # Summary + headless snapshot services
        self.headless_snapshot_service = HeadlessSnapshotService()
        self.maintenance_service = MaintenanceService(
            client=self.client,
            output_poller=self.output_poller,
            poller_watch_interval_s=5.0,
            codex_transcript_watch_interval_s=CODEX_TRANSCRIPT_WATCH_INTERVAL_S,
        )

        # Initialize AgentCoordinator for agent events and cross-computer orchestration
        self.agent_coordinator = AgentCoordinator(
            self.client,
            self.tts_manager,
            self.headless_snapshot_service,
        )

        # Wire direct agent event handler — replaces event bus for AGENT_EVENT.
        # polling_coordinator and redis_transport call this directly instead of
        # fire-and-forget through event_bus.emit().
        self.client.agent_event_handler = self.agent_coordinator.handle_event
        self.client.agent_coordinator = self.agent_coordinator

        # Auto-discover and register event handlers (SESSION_*, ERROR only —
        # AGENT_EVENT is routed directly via adapter_client.agent_event_handler)
        for attr_name in dir(TeleClaudeEvents):
            if attr_name.startswith("_"):
                continue

            event_value = getattr(TeleClaudeEvents, attr_name)
            if not isinstance(event_value, str):
                continue

            # AGENT_EVENT bypasses event bus — routed directly
            if event_value == TeleClaudeEvents.AGENT_EVENT:
                continue

            handler_name = f"_handle_{event_value}"
            handler = getattr(self, handler_name, None)

            if handler and callable(handler):
                event_bus.subscribe(cast(EventType, event_value), handler)
                logger.debug("Auto-registered handler: %s → %s", event_value, handler_name)
            else:
                logger.debug("No handler for event: %s (skipped)", event_value)

        # Register non-TeleClaudeEvents handlers
        event_bus.subscribe("system_command", self._handle_system_command)

        # Note: Adapters are loaded in client.start(), not here

        # Shutdown event for graceful termination
        self.shutdown_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task[object]] = set()
        # Per-session outbox processing: one serial worker per session, parallel across sessions.
        self._session_outbox_queues: dict[str, _HookOutboxSessionQueue] = {}
        self._session_outbox_workers: dict[str, asyncio.Task[None]] = {}
        self._hook_outbox_processed_count = 0
        self._hook_outbox_coalesced_count = 0
        self._hook_outbox_lag_samples_s: list[float] = []
        self._hook_outbox_last_summary_at = time.monotonic()
        self._hook_outbox_last_backlog_warn_at: dict[str, float] = {}
        self._hook_outbox_last_lag_warn_at: dict[str, float] = {}
        self.resource_monitor_task: asyncio.Task[object] | None = None
        self.launchd_watch_task: asyncio.Task[object] | None = None
        self._start_time = time.time()
        self._shutdown_reason: str | None = None
        self.hook_outbox_task: asyncio.Task[object] | None = None
        self.notification_outbox_task: asyncio.Task[object] | None = None
        self.todo_watcher_task: asyncio.Task[object] | None = None
        self.codex_transcript_watch_task: asyncio.Task[object] | None = None
        self.webhook_delivery_task: asyncio.Task[object] | None = None
        self.channel_subscription_worker_task: asyncio.Task[object] | None = None

        self.lifecycle = DaemonLifecycle(
            client=self.client,
            cache=self.cache,
            shutdown_event=self.shutdown_event,
            task_registry=self.task_registry,
            runtime_settings=self.runtime_settings,
            log_background_task_exception=self._log_background_task_exception,
            init_voice_handler=init_voice_handler,
            api_restart_max=API_RESTART_MAX,
            api_restart_window_s=API_RESTART_WINDOW_S,
            api_restart_backoff_s=API_RESTART_BACKOFF_S,
        )

        self.monitoring_service = MonitoringService(
            lifecycle=self.lifecycle,
            task_registry=self.task_registry,
            shutdown_event=self.shutdown_event,
            start_time=self._start_time,
            resource_snapshot_interval_s=RESOURCE_SNAPSHOT_INTERVAL_S,
            launchd_watch_interval_s=LAUNCHD_WATCH_INTERVAL_S,
            db_path=db.db_path,
        )

    def _log_background_task_exception(self, task_name: str) -> Callable[[asyncio.Task[object]], None]:
        """Return a done-callback that logs unexpected background task failures."""

        def _on_done(task: asyncio.Task[object]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                return
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Background task '%s' crashed: %s", task_name, e, exc_info=True)

        return _on_done

    def _track_background_task(self, task: asyncio.Task[object], label: str) -> None:
        """Track background tasks so failures are logged and tasks aren't lost."""
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Background task failed (%s): %s", label, exc, exc_info=True)

        task.add_done_callback(_on_done)

    @staticmethod
    def _classify_hook_event(event_type: str) -> Literal["critical", "bursty"]:
        """Classify hook events for queueing policy."""
        if event_type in HOOK_EVENT_CLASS_CRITICAL:
            return "critical"
        if event_type in HOOK_EVENT_CLASS_BURSTY:
            return "bursty"
        # Default non-critical events to bursty until promoted explicitly.
        return "bursty"

    @staticmethod
    def _percentile(samples: list[float], pct: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = int(round((len(ordered) - 1) * pct))
        index = max(0, min(index, len(ordered) - 1))
        return ordered[index]

    @staticmethod
    def _find_bursty_coalesce_index(pending: list[_HookOutboxQueueItem], event_type: str) -> int | None:
        """Find a same-type bursty item after the latest critical boundary."""
        last_critical = -1
        for idx in range(len(pending) - 1, -1, -1):
            if pending[idx].classification == "critical":
                last_critical = idx
                break

        for idx in range(len(pending) - 1, last_critical, -1):
            item = pending[idx]
            if item.classification == "bursty" and item.event_type == event_type:
                return idx
        return None

    @staticmethod
    def _find_oldest_bursty_index(pending: list[_HookOutboxQueueItem]) -> int | None:
        for idx, item in enumerate(pending):
            if item.classification == "bursty":
                return idx
        return None

    def _maybe_warn_hook_backlog(self, session_id: str, depth: int) -> None:
        if depth < HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD:
            return
        now = time.monotonic()
        last_warn = self._hook_outbox_last_backlog_warn_at.get(session_id, 0.0)
        if (now - last_warn) < HOOK_OUTBOX_WARN_LOG_INTERVAL_S:
            return
        self._hook_outbox_last_backlog_warn_at[session_id] = now
        logger.warning(
            "Hook outbox backlog threshold exceeded",
            session_id=session_id[:8],
            queue_depth=depth,
            threshold=HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD,
        )

    def _record_hook_lag_sample(self, row: HookOutboxRow) -> None:
        created_at_raw = row.get("created_at")
        if not isinstance(created_at_raw, str) or not created_at_raw:
            return
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = created_at.astimezone(timezone.utc)

        lag_s = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
        self._hook_outbox_lag_samples_s.append(lag_s)
        overflow = len(self._hook_outbox_lag_samples_s) - HOOK_OUTBOX_MAX_LAG_SAMPLES
        if overflow > 0:
            del self._hook_outbox_lag_samples_s[:overflow]

        session_id = str(row.get("session_id") or "")
        if not session_id or lag_s < HOOK_OUTBOX_LAG_WARN_THRESHOLD_S:
            return
        now = time.monotonic()
        last_warn = self._hook_outbox_last_lag_warn_at.get(session_id, 0.0)
        if (now - last_warn) < HOOK_OUTBOX_WARN_LOG_INTERVAL_S:
            return
        self._hook_outbox_last_lag_warn_at[session_id] = now
        logger.warning(
            "Hook outbox lag threshold exceeded",
            session_id=session_id[:8],
            lag_s=round(lag_s, 3),
            threshold_s=HOOK_OUTBOX_LAG_WARN_THRESHOLD_S,
            event_type=str(row.get("event_type") or ""),
        )

    def _maybe_log_hook_outbox_summary(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._hook_outbox_last_summary_at) < HOOK_OUTBOX_SUMMARY_INTERVAL_S:
            return

        queue_depth = 0
        for state in self._session_outbox_queues.values():
            queue_depth += len(state.pending)

        if (
            not force
            and self._hook_outbox_processed_count == 0
            and self._hook_outbox_coalesced_count == 0
            and queue_depth == 0
        ):
            self._hook_outbox_last_summary_at = now
            return

        p95_lag = self._percentile(self._hook_outbox_lag_samples_s, 0.95)
        p99_lag = self._percentile(self._hook_outbox_lag_samples_s, 0.99)
        logger.info(
            "Hook outbox summary",
            processed=self._hook_outbox_processed_count,
            coalesced=self._hook_outbox_coalesced_count,
            queue_depth=queue_depth,
            lag_sample_count=len(self._hook_outbox_lag_samples_s),
            p95_lag_s=round(p95_lag, 3) if p95_lag is not None else None,
            p99_lag_s=round(p99_lag, 3) if p99_lag is not None else None,
        )
        self._hook_outbox_last_summary_at = now

    def _hook_outbox_backoff(self, attempt: int) -> float:
        """Compute exponential backoff for hook outbox retries."""
        safe_attempt = max(1, attempt)
        delay: float = float(HOOK_OUTBOX_BASE_BACKOFF_S) * (2.0 ** (safe_attempt - 1))
        return min(delay, float(HOOK_OUTBOX_MAX_BACKOFF_S))

    def _is_retryable_hook_error(self, exc: Exception) -> bool:
        """Return True if hook dispatch errors should be retried."""
        if isinstance(exc, ValueError) and "not found" in str(exc):
            return False
        if isinstance(exc, json.JSONDecodeError) and "Extra data" in str(exc):
            return False
        return True

    async def _ensure_headless_session(
        self,
        session_id: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> Session:
        """Create a headless session row for standalone hook events."""
        native_log_file = data.get("native_log_file") or data.get("transcript_path")
        native_session_id = data.get("native_session_id") or data.get("session_id")
        agent_name = data.get("agent_name")
        agent_str = str(agent_name) if isinstance(agent_name, str) and agent_name else None

        workdir = None
        raw_cwd = data.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd:
            workdir = raw_cwd

        project_path = None
        subdir = None
        if workdir:
            trusted_dirs = [d.path for d in config.computer.get_all_trusted_dirs()]
            project_path, subdir = split_project_path_and_subdir(workdir, trusted_dirs)

        title = "Standalone"
        if project_path:
            title = get_short_project_name(project_path, subdir)

        logger.info(
            "Creating headless session",
            session_id=session_id[:8],
            agent=agent_str,
            project_path=project_path or "",
        )
        session = await db.create_headless_session(
            session_id=session_id,
            computer_name=config.computer.name,
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            active_agent=agent_str,
            native_session_id=str(native_session_id) if native_session_id else None,
            native_log_file=str(native_log_file) if native_log_file else None,
            project_path=project_path,
            subdir=subdir,
        )

        event_bus.emit(
            TeleClaudeEvents.SESSION_STARTED,
            SessionLifecycleContext(session_id=session_id),
        )

        return session

    def _is_codex_headless_bootstrap_event(
        self,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> bool:
        """Return True when a missing session should still be materialized for Codex headless hooks.

        TODO(codex-headless): remove this special-case path once Codex emits a stable
        session_start-equivalent event that can be used to create the headless session.
        """
        if event_type != AgentHookEvents.AGENT_STOP:
            return False

        raw_agent_name = data.get("agent_name")
        if not isinstance(raw_agent_name, str) or raw_agent_name.strip().lower() != AgentName.CODEX.value:
            return False

        raw_native_session_id = data.get("native_session_id")
        return isinstance(raw_native_session_id, str) and bool(raw_native_session_id.strip())

    async def _dispatch_hook_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> None:
        """Dispatch a hook event directly global Event Bus."""
        session = await db.get_session(session_id)
        if not session:
            if event_type != AgentHookEvents.AGENT_SESSION_START and not self._is_codex_headless_bootstrap_event(
                event_type, data
            ):
                logger.debug(
                    "Ignoring hook event for unknown session (not session_start)",
                    session_id=session_id[:8],
                    event_type=event_type,
                )
                return
            session = await self._ensure_headless_session(session_id, data)
        elif session.lifecycle_status == "closed":
            logger.debug(
                "Ignoring hook event for closed session",
                session_id=session_id[:8],
                event_type=event_type,
            )
            return
        elif session.lifecycle_status == "headless" and session.last_input_origin != InputOrigin.TERMINAL.value:
            await db.update_session(session_id, last_input_origin=InputOrigin.TERMINAL.value)
            session = await db.get_session(session_id) or session

        transcript_path = data.get("transcript_path")
        native_session_id = data.get("native_session_id")
        native_log_file = data.get("native_log_file")
        raw_agent_name = data.get("agent_name")
        normalized_agent_name = raw_agent_name.strip().lower() if isinstance(raw_agent_name, str) else ""

        has_transcript_path = isinstance(transcript_path, str) and bool(transcript_path)
        has_native_log = isinstance(native_log_file, str) and bool(native_log_file)
        if (
            not has_transcript_path
            and not has_native_log
            and normalized_agent_name == AgentName.CODEX.value
            and isinstance(native_session_id, str)
            and native_session_id
        ):
            discovered_path = discover_codex_transcript_path(native_session_id)
            if discovered_path:
                native_log_file = discovered_path
                data["native_log_file"] = discovered_path
                data["transcript_path"] = discovered_path
                transcript_path = discovered_path
                has_transcript_path = True
                logger.debug(
                    "Resolved Codex transcript in hook worker",
                    session_id=session_id[:8],
                    native_session_id=native_session_id[:8],
                    path=discovered_path,
                )
        elif not has_transcript_path and has_native_log and isinstance(native_log_file, str):
            transcript_path = native_log_file
            data["transcript_path"] = native_log_file
            has_transcript_path = True

        update_kwargs = {}
        if normalized_agent_name in AgentName.choices() and session.active_agent != normalized_agent_name:
            update_kwargs["active_agent"] = normalized_agent_name
        if isinstance(transcript_path, str) and transcript_path:
            update_kwargs["native_log_file"] = transcript_path
        if isinstance(native_log_file, str) and native_log_file:
            update_kwargs["native_log_file"] = native_log_file
        if isinstance(native_session_id, str) and native_session_id:
            update_kwargs["native_session_id"] = native_session_id

        if update_kwargs:
            await db.update_session(session_id, **update_kwargs)

        # Headless sessions have no tmux — skip output polling to avoid spawning one.
        if session.tmux_session_name:
            await self._ensure_output_polling(session)

        if event_type not in AgentHookEvents.ALL:
            logger.debug("Transcript capture event handled", event=event_type, session=session_id[:8])
            return

        if event_type == AgentHookEvents.AGENT_ERROR:
            severity = data.get("severity")
            retryable = data.get("retryable")
            code = data.get("code")
            context = ErrorEventContext(
                session_id=session_id,
                message=str(data.get("message", "")),
                source=str(data.get("source")) if "source" in data else None,
                details=data.get("details") if isinstance(data.get("details"), dict) else None,
                severity=severity if isinstance(severity, str) else "error",
                retryable=retryable if isinstance(retryable, bool) else False,
                code=code if isinstance(code, str) else None,
            )
            event_bus.emit(TeleClaudeEvents.ERROR, context)
        else:
            context = AgentEventContext(
                session_id=session_id,
                event_type=cast(AgentHookEvents, event_type),
                data=build_agent_payload(cast(AgentHookEvents, event_type), data),
            )
            # Directly await coordinator — outbox serialization depends on this completing
            # before the item is marked delivered. event_bus.emit would fire-and-forget.
            await self._handle_agent_event(TeleClaudeEvents.AGENT_EVENT, context)

    async def _wal_checkpoint_loop(self) -> None:
        """Periodically checkpoint the SQLite WAL to prevent unbounded growth."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(300)  # 5 minutes
            if self.shutdown_event.is_set():
                break
            try:
                await db.wal_checkpoint()
            except Exception as exc:
                logger.warning("WAL checkpoint failed: %s", exc)

    async def _hook_outbox_worker(self) -> None:
        """Drain hook outbox for durable, restart-safe delivery.

        Dispatch model:
        - One logical serial worker per session (strict ordering inside session).
        - Different sessions are handled in parallel.
        """
        try:
            while not self.shutdown_event.is_set():
                now = datetime.now(timezone.utc)
                now_iso = now.isoformat()
                lock_cutoff = (now - timedelta(seconds=HOOK_OUTBOX_LOCK_TTL_S)).isoformat()
                rows = await db.fetch_hook_outbox_batch(now_iso, HOOK_OUTBOX_BATCH_SIZE, lock_cutoff)

                if not rows:
                    self._maybe_log_hook_outbox_summary()
                    await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
                    continue

                for row in rows:
                    if self.shutdown_event.is_set():
                        break
                    claimed = await db.claim_hook_outbox(row["id"], now_iso, lock_cutoff)
                    if not claimed:
                        continue

                    session_id = str(row["session_id"])
                    await self._enqueue_session_outbox_item(session_id, row)

                self._maybe_log_hook_outbox_summary()
        finally:
            self._maybe_log_hook_outbox_summary(force=True)

    async def _enqueue_session_outbox_item(
        self,
        session_id: str,
        row: HookOutboxRow,
    ) -> None:
        """Enqueue a claimed outbox row with bounded burst coalescing."""
        event_type = str(row.get("event_type") or "")
        row_id = int(row.get("id") or 0)
        classification = self._classify_hook_event(event_type)
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            queue_state = _HookOutboxSessionQueue()
            self._session_outbox_queues[session_id] = queue_state

        dropped_rows: list[HookOutboxRow] = []
        enqueued = True
        requeue_claimed_critical = False
        duplicate_claimed_row = False
        queue_depth = 0
        queue_item = _HookOutboxQueueItem(
            row=row,
            event_type=event_type,
            classification=classification,
        )

        async with queue_state.lock:
            pending = queue_state.pending
            claimed_row_ids = queue_state.claimed_row_ids

            # Ignore duplicate claims for rows already queued or currently in-flight.
            if row_id and row_id in claimed_row_ids:
                duplicate_claimed_row = True
                enqueued = False
            elif classification == "bursty":
                replace_idx = self._find_bursty_coalesce_index(pending, event_type)
                if replace_idx is not None:
                    replaced_row = pending[replace_idx].row
                    replaced_row_id = int(replaced_row.get("id") or 0)
                    dropped_rows.append(replaced_row)
                    if replaced_row_id:
                        claimed_row_ids.discard(replaced_row_id)
                    pending[replace_idx] = queue_item
                    if row_id:
                        claimed_row_ids.add(row_id)
                else:
                    if len(pending) >= HOOK_OUTBOX_SESSION_MAX_PENDING:
                        drop_idx = self._find_oldest_bursty_index(pending)
                        if drop_idx is not None:
                            dropped_row = pending.pop(drop_idx).row
                            dropped_row_id = int(dropped_row.get("id") or 0)
                            dropped_rows.append(dropped_row)
                            if dropped_row_id:
                                claimed_row_ids.discard(dropped_row_id)
                        else:
                            # Critical-only backlog: preserve critical order, drop incoming bursty.
                            dropped_rows.append(row)
                            enqueued = False
                    if enqueued:
                        pending.append(queue_item)
                        if row_id:
                            claimed_row_ids.add(row_id)
            else:
                while len(pending) >= HOOK_OUTBOX_SESSION_MAX_PENDING:
                    drop_idx = self._find_oldest_bursty_index(pending)
                    if drop_idx is None:
                        # Queue is full of critical rows. Keep the claimed row durable in DB and retry later.
                        requeue_claimed_critical = True
                        enqueued = False
                        break
                    dropped_row = pending.pop(drop_idx).row
                    dropped_row_id = int(dropped_row.get("id") or 0)
                    dropped_rows.append(dropped_row)
                    if dropped_row_id:
                        claimed_row_ids.discard(dropped_row_id)
                if enqueued:
                    pending.append(queue_item)
                    if row_id:
                        claimed_row_ids.add(row_id)

            queue_depth = len(pending)
            if enqueued:
                queue_state.notify.set()

        if dropped_rows:
            self._hook_outbox_coalesced_count += len(dropped_rows)
            for dropped in dropped_rows:
                dropped_id = dropped["id"]
                await db.mark_hook_outbox_delivered(
                    dropped_id,
                    error=f"coalesced:{event_type or 'unknown'}",
                )

        if requeue_claimed_critical and not duplicate_claimed_row:
            logger.debug(
                "Hook outbox session queue at capacity; deferring claimed critical row",
                session_id=session_id[:8],
                row_id=row_id or row["id"],
                queue_depth=queue_depth,
                max_pending=HOOK_OUTBOX_SESSION_MAX_PENDING,
            )
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=HOOK_OUTBOX_POLL_INTERVAL_S)).isoformat()
            await db.mark_hook_outbox_failed(
                row_id=row_id or row["id"],
                attempt_count=int(row.get("attempt_count", 0)),
                next_attempt_at=retry_at,
                error="backpressure:session_queue_full",
            )

        self._maybe_warn_hook_backlog(session_id, queue_depth)

        worker = self._session_outbox_workers.get(session_id)
        if worker and not worker.done():
            return

        task = asyncio.create_task(self._run_session_outbox_worker(session_id))
        self._session_outbox_workers[session_id] = task
        self._track_background_task(task, f"outbox-worker:{session_id[:8]}")

    async def _run_session_outbox_worker(self, session_id: str) -> None:
        """Process claimed outbox rows serially for a single session."""
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            return

        try:
            while not self.shutdown_event.is_set():
                row: HookOutboxRow | None = None
                queue_depth = 0

                async with queue_state.lock:
                    if queue_state.pending:
                        row = queue_state.pending.pop(0).row
                    queue_depth = len(queue_state.pending)
                    if not queue_state.pending:
                        queue_state.notify.clear()

                if row is None:
                    try:
                        await asyncio.wait_for(queue_state.notify.wait(), timeout=HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S)
                    except asyncio.TimeoutError:
                        async with queue_state.lock:
                            if not queue_state.pending:
                                break
                    continue

                self._maybe_warn_hook_backlog(session_id, queue_depth)
                in_flight_row_id = int(row.get("id") or 0)
                try:
                    await self._process_outbox_item(row)
                finally:
                    if in_flight_row_id:
                        async with queue_state.lock:
                            queue_state.claimed_row_ids.discard(in_flight_row_id)
        finally:
            current = asyncio.current_task()
            if self._session_outbox_workers.get(session_id) is current:
                self._session_outbox_workers.pop(session_id, None)
            active_queue = self._session_outbox_queues.get(session_id)
            if active_queue is queue_state:
                async with queue_state.lock:
                    if not queue_state.pending and not queue_state.claimed_row_ids:
                        self._session_outbox_queues.pop(session_id, None)

    async def _process_outbox_item(
        self,
        row: HookOutboxRow,
    ) -> None:
        """Process a single outbox item. Handles its own success/failure lifecycle."""
        row_id = row["id"]
        try:
            payload = cast(
                dict[str, object],  # guard: loose-dict - Hook payload JSON
                json.loads(str(row["payload"])),
            )
        except json.JSONDecodeError as exc:
            logger.error("Hook outbox payload invalid", row_id=row_id, error=str(exc))
            await db.mark_hook_outbox_delivered(row_id, error=str(exc))
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
            return

        try:
            await self._dispatch_hook_event(str(row["session_id"]), str(row["event_type"]), payload)
            await db.mark_hook_outbox_delivered(row_id)
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            attempt = int(row.get("attempt_count", 0)) + 1
            error_str = str(exc)
            if not self._is_retryable_hook_error(exc):
                logger.error(
                    "Hook outbox event dropped (non-retryable)",
                    row_id=row_id,
                    attempt=attempt,
                    error=error_str,
                )
                await db.mark_hook_outbox_delivered(row_id, error=error_str)
                self._hook_outbox_processed_count += 1
                self._record_hook_lag_sample(row)
                return

            delay = self._hook_outbox_backoff(attempt)
            next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            logger.error(
                "Hook outbox dispatch failed (retrying)",
                row_id=row_id,
                attempt=attempt,
                next_attempt_in_s=round(delay, 2),
                error=error_str,
            )
            await db.mark_hook_outbox_failed(row_id, attempt, next_attempt, error_str)

    def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None:
        """Create and track a background task."""
        if len(self._background_tasks) > 200:
            logger.warning(
                "Background task cap reached (%d), skipping %s",
                len(self._background_tasks),
                label,
            )
            return
        task = asyncio.create_task(coro)
        self._track_background_task(task, label)

    async def _handle_session_closed(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_closed events - user closed session.

        Args:
            _event: Event type (always "session_closed") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context

        session = await db.get_session(ctx.session_id)
        if not session:
            logger.warning("Session %s not found for termination event", ctx.session_id[:8])
            return

        self._session_outbox_queues.pop(ctx.session_id, None)
        worker = self._session_outbox_workers.pop(ctx.session_id, None)
        if worker and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        polling_coordinator._cleanup_codex_input_state(ctx.session_id)

        logger.info("Handling session_closed for %s", ctx.session_id[:8])
        await session_cleanup.terminate_session(
            ctx.session_id,
            self.client,
            reason="topic_closed",
            session=session,
        )

    async def _handle_session_started(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_started events (headless snapshot bootstrap)."""
        session = await db.get_session(context.session_id)
        if not session:
            return

        if session.lifecycle_status != "headless":
            return

        await self.headless_snapshot_service.send_snapshot(session, reason="session_started", client=self.client)

    async def _handle_system_command(self, _event: str, context: SystemCommandContext) -> None:
        """Handler for SYSTEM_COMMAND events.

        System commands are daemon-level operations (deploy, restart, etc.)

        Args:
            _event: Event type (always "system_command") - unused but required by event handler signature
            context: System command context
        """
        ctx = context

        logger.info("Handling system command '%s' from %s", ctx.command, ctx.from_computer)

        if ctx.command == "deploy":
            await self._handle_deploy(ctx.args)
        elif ctx.command == "health_check":
            await self._handle_health_check()
        else:
            logger.warning("Unknown system command: %s", ctx.command)

    async def _handle_agent_event(self, _event: str, context: AgentEventContext) -> None:
        """Central handler for AGENT_EVENT."""
        await self.agent_coordinator.handle_event(context)

    async def _execute_auto_command(self, session_id: str, auto_command: str) -> dict[str, str]:
        """Execute a post-session auto_command and return status/message."""
        cmd_name, auto_args = parse_command_string(auto_command)

        if cmd_name and auto_command:
            session = await db.get_session(session_id)
            if not session or not session.last_input_origin:
                logger.error("Auto-command missing last_input_origin for session %s", session_id[:8])
                await db.update_session(
                    session_id,
                    last_message_sent=auto_command[:200],
                    last_message_sent_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                await db.update_session(
                    session_id,
                    last_message_sent=auto_command[:200],
                    last_message_sent_at=datetime.now(timezone.utc).isoformat(),
                    last_input_origin=session.last_input_origin,
                )

        if cmd_name == "agent_then_message":
            return await self._handle_agent_then_message(session_id, auto_args)

        if cmd_name == "agent" and auto_args:
            agent_name = auto_args.pop(0)
            await self.command_service.start_agent(
                StartAgentCommand(session_id=session_id, agent_name=agent_name, args=auto_args)
            )
            return {"status": "success"}

        if cmd_name == "agent_resume" and auto_args:
            agent_name = auto_args.pop(0)
            native_session_id = auto_args[0] if auto_args else None
            await self.command_service.resume_agent(
                ResumeAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    native_session_id=native_session_id,
                )
            )
            return {"status": "success"}

        logger.warning("Unknown or malformed auto_command: %s", auto_command)
        return {"status": "error", "message": f"Unknown or malformed auto_command: {auto_command}"}

    async def _bootstrap_session_resources(self, session_id: str, auto_command: str | None) -> None:
        """Create tmux + start polling + run auto command."""
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s missing during bootstrap", session_id[:8])
            return

        voice = await db.get_voice(session_id)
        voice_env_vars = get_voice_env_vars(voice) if voice else {}
        env_vars = voice_env_vars.copy()
        working_dir = resolve_working_dir(session.project_path, session.subdir)

        created = await tmux_bridge.ensure_tmux_session(
            name=session.tmux_session_name,
            working_dir=working_dir,
            session_id=session_id,
            env_vars=env_vars,
        )
        if not created:
            logger.error("Failed to create tmux session for %s", session_id[:8])
            await db.update_session(
                session_id,
                lifecycle_status="closed",
                closed_at=datetime.now(timezone.utc),
            )
            return

        # TTS session_start is triggered via event_bus (SESSION_STARTED event)
        await self._start_polling_for_session(session_id, session.tmux_session_name)

        # Run auto-command BEFORE transitioning to active so that process_message
        # callers waiting on the initializing gate see the transition only after
        # the startup command has been dispatched into tmux.
        auto_command_result: dict[str, str] | None = None
        if auto_command:
            try:
                auto_command_result = await self._execute_auto_command(session_id, auto_command)
            except Exception:
                logger.error(
                    "Bootstrap auto-command failed for session %s",
                    session_id[:8],
                    exc_info=True,
                )
                auto_command_result = {"status": "error"}

        # Transition non-headless sessions to active so they appear in listings.
        # Headless sessions stay "headless" until explicitly adopted by a UI adapter.
        if session.lifecycle_status != "headless":
            await db.update_session(session_id, lifecycle_status="active")

        logger.info(
            "Bootstrap complete for session %s: auto_command=%s result=%s",
            session_id[:8],
            bool(auto_command),
            auto_command_result.get("status") if auto_command_result else "n/a",
        )

    async def _handle_agent_then_message(self, session_id: str, args: list[str]) -> dict[str, str]:
        """Start agent, wait for TUI to stabilize, then inject message."""
        start_time = time.time()
        logger.debug("agent_then_message: started for session=%s", session_id[:8])

        if len(args) < 3:
            return {"status": "error", "message": "agent_then_message requires agent, thinking_mode, message"}

        agent_name = args[0]
        thinking_mode = args[1]
        message = " ".join(args[2:]).strip()
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        await db.update_session(
            session_id,
            last_message_sent=message[:200],
            last_message_sent_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.debug("agent_then_message: agent=%s mode=%s msg=%s", agent_name, thinking_mode, message[:50])

        # Fire-and-forget start command (don't wait for 1s driver sleep)
        t0 = time.time()
        await self.command_service.start_agent(
            StartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
                thinking_mode=thinking_mode,
                args=[],
            )
        )
        logger.debug("agent_then_message: agent_start took %.3fs", time.time() - t0)

        session = await db.get_session(session_id)
        if not session:
            return {"status": "error", "message": "Session not found after creation"}

        # Step 1: Wait for output to stabilize (TUI banner and startup output complete)
        # We integrate the "process running" check into stabilization logic.
        # Gemini gets a longer quiet window to ensure heavy initialization is done.
        logger.debug("agent_then_message: waiting for TUI to stabilize (session=%s)", session_id[:8])

        quiet_s = AGENT_START_STABILIZE_QUIET_S
        if agent_name == AgentName.GEMINI.value:
            quiet_s += max(0, GEMINI_START_EXTRA_DELAY_S)

        t1 = time.time()
        stabilized, _stable_tail = await self._wait_for_output_stable(
            session,
            AGENT_START_STABILIZE_TIMEOUT_S,
            quiet_s,
        )
        logger.debug("agent_then_message: stabilization took %.3fs", time.time() - t1)

        if not stabilized:
            logger.warning(
                "agent_then_message: stabilization timed out after %.1fs, proceeding anyway (session=%s)",
                AGENT_START_STABILIZE_TIMEOUT_S,
                session_id[:8],
            )

        # Verify agent is actually running before injecting message
        if not await tmux_io.is_process_running(session):
            logger.error("agent_then_message: process not running after stabilization (session=%s)", session_id[:8])
            return {"status": "error", "message": "Agent process exited/failed to start before message injection"}

        # Step 2: Inject the message immediately (TUI should be ready)
        logger.debug("agent_then_message: injecting message to session=%s", session_id[:8])

        sanitized_message = tmux_io.wrap_bracketed_paste(message, active_agent=agent_name)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        pasted = await tmux_io.process_text(
            session,
            sanitized_message,
            working_dir=working_dir,
            send_enter=True,  # Send Enter immediately
            active_agent=session.active_agent,
        )
        if not pasted:
            return {"status": "error", "message": "Failed to paste command into tmux"}

        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)

        # Step 3: Wait for command acceptance (Enter was already sent)
        accepted = await self._confirm_command_acceptance(session)
        if not accepted:
            logger.warning(
                "agent_then_message timed out waiting for command acceptance (session=%s)",
                session_id[:8],
            )
            return {"status": "error", "message": "Timeout waiting for command acceptance"}

        logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
        return {"status": "success", "message": "Message injected after agent start"}

    async def _pane_output_snapshot(self, session: Session) -> tuple[str, str]:
        output = await tmux_bridge.capture_pane(session.tmux_session_name)
        if not output:
            return "", ""
        tail = output[-UI_MESSAGE_MAX_CHARS:]
        digest = hashlib.sha256(tail.encode("utf-8", errors="replace")).hexdigest()
        return tail, digest

    async def _wait_for_output_stable(
        self,
        session: Session,
        timeout_s: float,
        quiet_s: float,
    ) -> tuple[bool, str]:
        """Wait for output to stop changing (stabilize).

        Polls tmux output and waits until:
        1. Output has changed from the initial state (indicating process started)
        2. Output hasn't changed for `quiet_s` seconds (indicating TUI loaded)

        Args:
            session: The session to monitor
            timeout_s: Maximum time to wait for stabilization
            quiet_s: How long output must be unchanged to be considered stable

        Returns:
            Tuple of (stabilized, last_output_tail)
        """
        deadline = time.monotonic() + timeout_s
        initial_tail, initial_digest = await self._pane_output_snapshot(session)
        last_tail, last_digest = initial_tail, initial_digest

        has_changed = False
        quiet_since = time.monotonic()

        while time.monotonic() < deadline:
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
            current_tail, current_digest = await self._pane_output_snapshot(session)

            if current_digest != last_digest:
                # Output changed
                has_changed = True
                last_tail, last_digest = current_tail, current_digest
                quiet_since = time.monotonic()
            elif has_changed and (time.monotonic() - quiet_since >= quiet_s):
                # Output changed at least once AND has been stable for quiet_s seconds
                logger.debug("Output stabilized after %.1fs quiet", quiet_s)
                return True, current_tail

        logger.debug("Output stabilization timed out after %.1fs (has_changed=%s)", timeout_s, has_changed)
        return False, last_tail

    @staticmethod
    def _summarize_output_change(before: str, after: str) -> OutputChangeSummary:
        if before == after:
            return OutputChangeSummary(changed=False, reason="identical")

        min_len = min(len(before), len(after))
        diff_index = None
        for idx in range(min_len):
            if before[idx] != after[idx]:
                diff_index = idx
                break
        if diff_index is None:
            diff_index = min_len

        snippet_len = 160
        before_snippet = before[max(0, diff_index - 40) : diff_index + snippet_len]
        after_snippet = after[max(0, diff_index - 40) : diff_index + snippet_len]

        return OutputChangeSummary(
            changed=True,
            before_len=len(before),
            after_len=len(after),
            diff_index=diff_index,
            before_snippet=repr(before_snippet),
            after_snippet=repr(after_snippet),
        )

    async def _wait_for_output_change(
        self,
        session: Session,
        before: str,
        before_digest: str,
        timeout_s: float,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_s
        last_tail = ""
        while time.monotonic() < deadline:
            current_tail, current_digest = await self._pane_output_snapshot(session)
            last_tail = current_tail
            if current_digest != before_digest:
                return True, current_tail
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
        return False, last_tail

    async def _wait_for_output_contains(
        self,
        session: Session,
        needle: str,
        timeout_s: float,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_s
        last_tail = ""
        while time.monotonic() < deadline:
            current_tail, _ = await self._pane_output_snapshot(session)
            last_tail = current_tail
            if needle and needle in current_tail:
                return True, current_tail
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
        return False, last_tail

    async def _confirm_command_acceptance(self, session: Session) -> bool:
        attempts = max(1, AGENT_START_CONFIRM_ENTER_ATTEMPTS)
        for attempt in range(attempts):
            before_tail, before_digest = await self._pane_output_snapshot(session)
            await tmux_io.send_enter(session)
            await asyncio.sleep(AGENT_START_ENTER_INTER_DELAY_S)
            await tmux_io.send_enter(session)

            changed, after_tail = await self._wait_for_output_change(
                session,
                before_tail,
                before_digest,
                AGENT_START_OUTPUT_CHANGE_TIMEOUT_S,
            )
            if changed:
                summary = self._summarize_output_change(before_tail, after_tail)
                logger.debug(
                    "agent_then_message acceptance output change: %s",
                    summary,
                )
                return True
            logger.trace(
                "agent_then_message no output change after enter attempt %d: tail=%s",
                attempt + 1,
                repr(after_tail[-160:]) if after_tail else "''",
            )

            if attempt < attempts - 1:
                await asyncio.sleep(AGENT_START_CONFIRM_ENTER_DELAY_S)
        return False

    async def _handle_error(self, _event: str, context: ErrorEventContext) -> None:
        """Handle error events (fail-fast contract violations, hook issues)."""
        if not context.session_id:
            logger.error("Error event without session: %s", context.message)
            return

        session = await db.get_session(context.session_id)
        if not session:
            logger.error("Error event for unknown session %s: %s", context.session_id[:8], context.message)
            return

        user_message = get_user_facing_error_message(context)
        if user_message is None:
            logger.debug(
                "Suppressing non-user-facing error event",
                session_id=context.session_id[:8],
                source=context.source,
                code=context.code,
            )
            return

        await self.client.send_message(session, f"❌ {user_message}", metadata=MessageMetadata())

    async def _handle_deploy(self, _args: DeployArgs) -> None:
        """Execute deployment: git pull + restart daemon via service manager.

        Args:
            _args: Deploy arguments (verify_health currently unused)
        """
        # Get Redis adapter for status updates
        redis_transport_base = self.client.adapters.get("redis")
        if not redis_transport_base:
            logger.error("Redis transport not available, cannot update deploy status")
            return
        deploy_service = DeployService(redis_transport=redis_transport_base)
        await deploy_service.deploy()

    async def _handle_health_check(self) -> None:
        """Handle health check requested."""
        logger.info("Health check requested")

    def _acquire_lock(self) -> None:
        """Acquire daemon lock using PID file with fcntl advisory locking.

        Production-grade approach: atomic, reliable, OS-standard.
        No unreliable ps aux grepping needed.

        Raises:
            DaemonLockError: If another daemon instance is already running
        """
        if self.pid_file_handle is not None:
            logger.debug("Daemon lock already held by current process")
            return

        try:
            # Open file for append+read (creates if doesn't exist, preserves inode)
            # This is critical: "a+" mode preserves the file's inode even if the file
            # was deleted, ensuring fcntl locks remain effective across processes
            self.pid_file_handle = open(self.pid_file, "a+", encoding="utf-8")

            # Try to acquire exclusive lock (non-blocking)
            try:
                fcntl.flock(self.pid_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                # Another process holds the lock
                self.pid_file_handle.close()
                self.pid_file_handle = None

                # Try to read the PID of the locking process
                try:
                    existing_pid = self.pid_file.read_text().strip()
                    raise DaemonLockError(
                        f"Another daemon instance is already running (PID: {existing_pid}). "
                        f"Stop it first or remove {self.pid_file} if it's stale."
                    ) from exc
                except (OSError, ValueError) as e:
                    raise DaemonLockError(
                        f"Another daemon instance is already running. "
                        f"Stop it first or remove {self.pid_file} if it's stale."
                    ) from e

            # Truncate file and write current PID (file is already locked)
            self.pid_file_handle.seek(0)
            self.pid_file_handle.truncate()
            self.pid_file_handle.write(str(os.getpid()))
            self.pid_file_handle.flush()
            logger.debug("Acquired daemon lock (PID: %s)", os.getpid())

            # Register cleanup
            atexit.register(self._release_lock)

        except OSError as e:
            if self.pid_file_handle:
                self.pid_file_handle.close()
                self.pid_file_handle = None
            raise DaemonLockError(f"Failed to acquire lock: {e}") from e

    def _release_lock(self) -> None:
        """Release daemon lock by closing file handle and removing PID file."""
        try:
            # Close file handle (automatically releases fcntl lock)
            if self.pid_file_handle:
                self.pid_file_handle.close()
                self.pid_file_handle = None
                logger.debug("Released daemon lock")

            # Remove PID file
            if self.pid_file.exists():
                self.pid_file.unlink()
        except OSError as e:
            logger.error("Failed to release lock: %s", e)

    async def _execute_terminal_command(
        self,
        session_id: str,
        command: str,
        _message_id: Optional[str] = None,
        start_polling: bool = True,
    ) -> bool:
        """Execute command in tmux and start polling if needed.

        Args:
            session_id: Session ID
            command: Command to execute
            _message_id: Message ID to cleanup (optional) - currently unused
            start_polling: Whether to start polling after command execution (default: True)

        Returns:
            True if successful, False otherwise
        """
        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.error("Session %s not found", session_id[:8])
            return False

        sanitized_command = tmux_io.wrap_bracketed_paste(command, active_agent=session.active_agent)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        success = await tmux_io.process_text(
            session,
            sanitized_command,
            working_dir=working_dir,
        )

        if not success:
            await self.client.send_message(session, f"Failed to execute command: {command}", metadata=MessageMetadata())
            logger.error("Failed to execute command in session %s: %s", session_id[:8], command)
            return False

        # Update activity
        await db.update_last_activity(session_id)

        # NOTE: Message cleanup now handled by TelegramAdapter pre/post handlers
        # - POST handler tracks message_id for deletion
        # - PRE handler deletes on NEXT user input (better UX - failed commands stay visible)

        # Start polling only if requested by handler
        # Handlers know whether their commands need polling (claude=long-running)
        if start_polling:
            await self._start_polling_for_session(session_id, session.tmux_session_name)

        logger.info("Executed command in session %s: %s (polling=%s)", session_id[:8], command, start_polling)
        return True

    async def _init_webhook_service(self) -> None:
        """Initialize the webhook service subsystem (contracts, handlers, dispatcher, bridge, delivery)."""

        contract_registry = ContractRegistry()
        handler_registry = HandlerRegistry()
        dispatcher = HookDispatcher(contract_registry, handler_registry, db.enqueue_webhook)
        bridge = EventBusBridge(dispatcher)
        delivery_worker = WebhookDeliveryWorker()
        project_cfg_path = config_path.parent / "teleclaude.yml"
        project_config = load_project_config(project_cfg_path)

        # Load contracts from DB
        await contract_registry.load_from_db()

        # Built-in inbound WhatsApp handling (global subscription handler).
        handler_registry.register("whatsapp_inbound", handle_whatsapp_event)
        await contract_registry.register(
            Contract(
                id="builtin-whatsapp-inbound",
                target=Target(handler="whatsapp_inbound"),
                source_criterion=PropertyCriterion(match="whatsapp"),
                type_criterion=PropertyCriterion(pattern="message.*"),
                source="programmatic",
            )
        )

        # Register built-in normalizers.
        normalizer_registry = NormalizerRegistry()
        register_builtin_normalizers(normalizer_registry)

        # Load config-driven contracts and inbound endpoints.
        # Contracts load regardless of API server availability; inbound routes require it.
        lifecycle_api_server = getattr(self.lifecycle, "api_server", None)
        app = getattr(lifecycle_api_server, "app", None)
        inbound_registry = None
        if app is not None:
            inbound_registry = InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)
        else:
            logger.warning("API server app unavailable; inbound webhooks will not be registered")
        await load_hooks_config(
            project_config.hooks.model_dump(),
            contract_registry,
            inbound_registry=inbound_registry,
        )

        if project_config.channel_subscriptions:
            redis_adapter = self.client.adapters.get("redis")
            if isinstance(redis_adapter, RedisTransport):
                try:
                    redis_client = await redis_adapter._get_redis()
                except Exception as exc:  # noqa: BLE001 - keep service startup resilient
                    logger.error(
                        "Failed to start channel subscription worker due to redis error",
                        error=str(exc),
                        exc_info=True,
                    )
                else:
                    self.channel_subscription_worker_task = asyncio.create_task(
                        run_subscription_worker(
                            redis=redis_client,
                            subscriptions=project_config.channel_subscriptions,
                            shutdown_event=self.shutdown_event,
                        )
                    )
                    self.channel_subscription_worker_task.add_done_callback(
                        self._log_background_task_exception("subscription_worker")
                    )
            else:
                logger.warning("Redis adapter unavailable; skipping channel subscription worker")

        # Wire contract registry into API routes
        set_contract_registry(contract_registry)

        # Subscribe bridge to event bus
        bridge.register(event_bus)

        # Start delivery worker
        self.webhook_delivery_task = asyncio.create_task(delivery_worker.run(self.shutdown_event))
        self.webhook_delivery_task.add_done_callback(self._log_background_task_exception("webhook_delivery"))
        self._webhook_delivery_worker = delivery_worker
        self._contract_registry = contract_registry

        # Start contract TTL sweep (every 60s)
        self._contract_sweep_task = asyncio.create_task(self._contract_sweep_loop())
        self._contract_sweep_task.add_done_callback(self._log_background_task_exception("contract_sweep"))

        logger.info("Webhook service initialized (%d contracts loaded)", len(contract_registry._cache))

    async def _contract_sweep_loop(self) -> None:
        """Periodically deactivate expired contracts."""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(60)
                if hasattr(self, "_contract_registry") and self._contract_registry:
                    await self._contract_registry.sweep_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Contract sweep failed", exc_info=True)

    async def start(self) -> None:
        """Start the daemon."""
        # Safety net: enforce single-instance lock even for direct start() callers.
        # main() already acquires this lock, so _acquire_lock() is idempotent.
        self._acquire_lock()
        logger.info("Starting TeleClaude daemon...")
        try:
            await self.lifecycle.startup()

            # Start periodic cleanup task (runs every hour)
            self.cleanup_task = asyncio.create_task(self.maintenance_service.periodic_cleanup())
            self.cleanup_task.add_done_callback(self._log_background_task_exception("periodic_cleanup"))
            logger.info("Periodic cleanup task started (72h session lifecycle)")

            # Start polling watcher (keeps pollers aligned with tmux foreground state)
            self.poller_watch_task = asyncio.create_task(self.maintenance_service.poller_watch_loop())
            self.poller_watch_task.add_done_callback(self._log_background_task_exception("poller_watch"))
            logger.info("Poller watch task started")

            self.hook_outbox_task = asyncio.create_task(self._hook_outbox_worker())
            self.hook_outbox_task.add_done_callback(self._log_background_task_exception("hook_outbox"))
            logger.info("Hook outbox worker started")

            if CODEX_TRANSCRIPT_WATCH_INTERVAL_S > 0:
                self.codex_transcript_watch_task = asyncio.create_task(
                    self.maintenance_service.codex_transcript_watch_loop()
                )
                self.codex_transcript_watch_task.add_done_callback(
                    self._log_background_task_exception("codex_transcript_watch")
                )
                logger.info("Codex transcript watch task started (interval=%.1fs)", CODEX_TRANSCRIPT_WATCH_INTERVAL_S)
            else:
                logger.info("Codex transcript watch disabled (interval=%.1fs)", CODEX_TRANSCRIPT_WATCH_INTERVAL_S)

            self.notification_outbox_task = asyncio.create_task(
                NotificationOutboxWorker(
                    db=db,
                    shutdown_event=self.shutdown_event,
                    poll_interval_s=NOTIFICATION_OUTBOX_POLL_INTERVAL_S,
                    batch_size=NOTIFICATION_OUTBOX_BATCH_SIZE,
                    lock_ttl_s=NOTIFICATION_OUTBOX_LOCK_TTL_S,
                    base_backoff_s=NOTIFICATION_OUTBOX_BASE_BACKOFF_S,
                    max_backoff_s=NOTIFICATION_OUTBOX_MAX_BACKOFF_S,
                ).run()
            )
            self.notification_outbox_task.add_done_callback(self._log_background_task_exception("notification_outbox"))
            logger.info("Notification outbox worker started")

            # Initialize webhook service subsystem
            try:
                await self._init_webhook_service()
            except Exception:
                logger.error("Webhook service initialization failed, continuing without webhooks", exc_info=True)

            # Wire Redis transport into channels API routes
            redis_adapter = self.client.adapters.get("redis")
            if redis_adapter:
                from teleclaude.channels.api_routes import set_redis_transport
                from teleclaude.transport.redis_transport import RedisTransport as _RT

                if isinstance(redis_adapter, _RT):
                    set_redis_transport(redis_adapter)
            self.resource_monitor_task = asyncio.create_task(self.monitoring_service.resource_monitor_loop())
            self.resource_monitor_task.add_done_callback(self._log_background_task_exception("resource_monitor"))
            logger.info("Resource monitor started (interval=%.0fs)", RESOURCE_SNAPSHOT_INTERVAL_S)

            self._wal_checkpoint_task = asyncio.create_task(self._wal_checkpoint_loop())
            self._wal_checkpoint_task.add_done_callback(self._log_background_task_exception("wal_checkpoint"))
            logger.info("WAL checkpoint task started (interval=300s)")

            todo_watcher = TodoWatcher(self.cache)
            self.todo_watcher_task = asyncio.create_task(todo_watcher.run())
            self.todo_watcher_task.add_done_callback(self._log_background_task_exception("todo_watcher"))
            logger.info("Todo watcher task started")

            self.monitoring_service.log_resource_snapshot("startup")

            if LAUNCHD_WATCH_ENABLED:
                self.launchd_watch_task = asyncio.create_task(self.monitoring_service.launchd_watch_loop())
                self.launchd_watch_task.add_done_callback(self._log_background_task_exception("launchd_watch"))
                logger.info("Launchd watch task started (interval=%.0fs)", LAUNCHD_WATCH_INTERVAL_S)

            logger.info("TeleClaude is running. Press Ctrl+C to stop.")
        except Exception:
            # Direct start() callers may not run through main() finally.
            # Release lock on startup failure to avoid stale lock ownership.
            self._release_lock()
            raise

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping TeleClaude daemon...")

        # Stop periodic cleanup task
        if hasattr(self, "cleanup_task"):
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Periodic cleanup task stopped")

        # Stop poller watch task
        if hasattr(self, "poller_watch_task"):
            self.poller_watch_task.cancel()
            try:
                await self.poller_watch_task
            except asyncio.CancelledError:
                pass
            logger.info("Poller watch task stopped")

        if self.hook_outbox_task:
            self.hook_outbox_task.cancel()
            try:
                await self.hook_outbox_task
            except asyncio.CancelledError:
                pass
            logger.info("Hook outbox worker stopped")

        if self.codex_transcript_watch_task:
            self.codex_transcript_watch_task.cancel()
            try:
                await self.codex_transcript_watch_task
            except asyncio.CancelledError:
                pass
            logger.info("Codex transcript watch task stopped")

        if self.notification_outbox_task:
            self.notification_outbox_task.cancel()
            try:
                await self.notification_outbox_task
            except asyncio.CancelledError:
                pass
            logger.info("Notification outbox worker stopped")

        if self._session_outbox_workers:
            workers = list(self._session_outbox_workers.values())
            self._session_outbox_workers.clear()
            self._session_outbox_queues.clear()
            for worker in workers:
                worker.cancel()
            for worker in workers:
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            logger.info("Session outbox workers stopped (%d)", len(workers))

        if self.webhook_delivery_task:
            self.webhook_delivery_task.cancel()
            try:
                await self.webhook_delivery_task
            except asyncio.CancelledError:
                pass
            logger.info("Webhook delivery worker stopped")

        if self.channel_subscription_worker_task:
            self.channel_subscription_worker_task.cancel()
            try:
                await self.channel_subscription_worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Channel subscription worker stopped")

        if hasattr(self, "_webhook_delivery_worker"):
            await self._webhook_delivery_worker.close()

        if self.resource_monitor_task:
            self.resource_monitor_task.cancel()
            try:
                await self.resource_monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Resource monitor stopped")

        if hasattr(self, "_wal_checkpoint_task") and self._wal_checkpoint_task:
            self._wal_checkpoint_task.cancel()
            try:
                await self._wal_checkpoint_task
            except asyncio.CancelledError:
                pass
            logger.info("WAL checkpoint task stopped")

        if self.todo_watcher_task:
            self.todo_watcher_task.cancel()
            try:
                await self.todo_watcher_task
            except asyncio.CancelledError:
                pass
            logger.info("Todo watcher task stopped")

        if self.launchd_watch_task:
            self.launchd_watch_task.cancel()
            try:
                await self.launchd_watch_task
            except asyncio.CancelledError:
                pass
            logger.info("Launchd watch task stopped")

        # Shutdown task registry (cancel all tracked background tasks)
        if hasattr(self, "task_registry"):
            await self.task_registry.shutdown(timeout=5.0)
            logger.info("Task registry shutdown complete")

        await self.lifecycle.shutdown()

        self._release_lock()
        logger.info("Daemon stopped")

    def request_shutdown(self, reason: str) -> None:
        """Request graceful shutdown and capture diagnostics."""
        self._shutdown_reason = reason
        self.client.mark_shutting_down()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.shutdown_event.set()
            return

        loop.call_soon_threadsafe(self.shutdown_event.set)
        loop.call_soon_threadsafe(self.monitoring_service.log_resource_snapshot, f"shutdown:{reason}")

    async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None:
        """Wrapper around polling_coordinator.schedule_polling (creates background task).

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
        """
        await polling_coordinator.schedule_polling(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            output_poller=self.output_poller,
            adapter_client=self.client,  # Use AdapterClient for multi-adapter broadcasting
            get_output_file=get_output_file,
        )

    async def _ensure_output_polling(self, session: Session) -> None:
        if await polling_coordinator.is_polling(session.session_id):
            return
        if not await self.maintenance_service.ensure_tmux_session(session):
            logger.warning("Tmux session missing for %s; polling skipped", session.session_id[:8])
            return

        await self._poll_and_send_output(session.session_id, session.tmux_session_name)

    async def _start_polling_for_session(self, session_id: str, tmux_session_name: str) -> None:
        session = await db.get_session(session_id)
        if session:
            await self._ensure_output_polling(session)
            return
        await self._poll_and_send_output(session_id, tmux_session_name)


async def main() -> None:
    """Main entry point."""
    # Find .env file for daemon constructor
    base_dir = Path(__file__).parent.parent
    env_path = base_dir / ".env"

    # Note: .env already loaded at module import time (before config expansion)

    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    setup_logging(level=log_level)
    logger.info("Starting TeleClaude Daemon (version=v2-append-only-v3)")

    # Create daemon
    daemon = TeleClaudeDaemon(str(env_path))

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum: int, _frame: object) -> None:
        """Handle termination signals."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s signal...", sig_name)
        daemon.request_shutdown(sig_name)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Acquire lock to prevent multiple instances (non-retryable)
        daemon._acquire_lock()

        # Start daemon with retry logic for transient network errors
        for attempt in range(STARTUP_MAX_RETRIES):
            try:
                await daemon.start()
                break  # Success - exit retry loop
            except Exception as e:
                # Non-retryable errors fail immediately
                if not _is_retryable_startup_error(e):
                    logger.error("Daemon startup failed (non-retryable): %s", e, exc_info=True)
                    sys.exit(1)

                # Last attempt exhausted
                if attempt == STARTUP_MAX_RETRIES - 1:
                    logger.error(
                        "Daemon startup failed after %d attempts: %s",
                        STARTUP_MAX_RETRIES,
                        e,
                        exc_info=True,
                    )
                    sys.exit(1)

                # Retry with exponential backoff
                delay = STARTUP_RETRY_DELAYS[attempt]
                logger.warning(
                    "Startup failed (attempt %d/%d): %s. Retrying in %ds...",
                    attempt + 1,
                    STARTUP_MAX_RETRIES,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        # Wait for shutdown signal
        await daemon.shutdown_event.wait()

    except DaemonLockError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal...")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        try:
            await daemon.stop()
        except Exception as e:
            logger.error("Error during daemon stop: %s", e)
        finally:
            daemon._release_lock()


if __name__ == "__main__":
    asyncio.run(main())
