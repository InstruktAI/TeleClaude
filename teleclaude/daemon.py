"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import hashlib
import inspect
import json
import os
import signal
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude import __version__

_MODULE_IMPORT_STARTED_AT = time.perf_counter()
_IMPORT_TIMINGS: list[tuple[str, float, float]] = []
logger = get_logger("teleclaude.daemon")

if TYPE_CHECKING:
    from teleclaude.hooks.dispatcher import HookDispatcher


def _record_import_timing(label: str, started_at: float) -> None:
    finished_at = time.perf_counter()
    _IMPORT_TIMINGS.append((label, finished_at - started_at, finished_at - _MODULE_IMPORT_STARTED_AT))


def _emit_import_timing_logs() -> None:
    for label, dt, since_module_start in _IMPORT_TIMINGS:
        logger.trace(
            "[PERF] daemon import %s dt=%.3f since_module_start=%.3f",
            label,
            dt,
            since_module_start,
        )
        if dt >= 1.0:
            logger.warning("Slow daemon import: module=%s dt=%.3fs", label, dt)


_t = time.perf_counter()
import teleclaude.observability.httpx_runtime_debug as _httpx_runtime_debug

_record_import_timing("teleclaude.observability.httpx_runtime_debug", _t)

_t = time.perf_counter()
from teleclaude.chiptunes.manager import ChiptunesManager
from teleclaude.chiptunes.types import ChiptunesState

_record_import_timing("teleclaude.chiptunes.manager", _t)

_t = time.perf_counter()
from teleclaude.config import (  # config.py loads .env at import time
    WORKING_DIR,
    config,
    config_path,
    dotenv_path,
    reload_config,
    restart_required_sections,
)
from teleclaude.core.config_watcher import ConfigWatcher

_record_import_timing("teleclaude.config", _t)

_t = time.perf_counter()
from teleclaude.config.runtime_settings import RuntimeSettings

_record_import_timing("teleclaude.config.runtime_settings", _t)

_t = time.perf_counter()
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, voice_message_handler

_record_import_timing("teleclaude.core bundle", _t)

_t = time.perf_counter()
from teleclaude.core.adapter_client import AdapterClient

_record_import_timing("teleclaude.core.adapter_client", _t)

_t = time.perf_counter()
from teleclaude.core.agent_coordinator import AgentCoordinator

_record_import_timing("teleclaude.core.agent_coordinator", _t)

_t = time.perf_counter()
from teleclaude.core.cache import DaemonCache

_record_import_timing("teleclaude.core.cache", _t)

_t = time.perf_counter()
from teleclaude.core.command_registry import init_command_service

_record_import_timing("teleclaude.core.command_registry", _t)

_t = time.perf_counter()
from teleclaude.core.command_service import CommandService

_record_import_timing("teleclaude.core.command_service", _t)

_t = time.perf_counter()
from teleclaude.core.db import db

_record_import_timing("teleclaude.core.db", _t)

_t = time.perf_counter()
from teleclaude.services.process_janitor import ProcessJanitorService
from teleclaude.services.process_janitor.service import ProcessJanitorSettings

_record_import_timing("teleclaude.services.process_janitor", _t)

_t = time.perf_counter()
from teleclaude.core.event_bus import event_bus

_record_import_timing("teleclaude.core.event_bus", _t)

_t = time.perf_counter()
from teleclaude.core.events import TeleClaudeEvents

_record_import_timing("teleclaude.core.events", _t)

_t = time.perf_counter()
from teleclaude.core.lifecycle import DaemonLifecycle

_record_import_timing("teleclaude.core.lifecycle", _t)

_t = time.perf_counter()
from teleclaude.core.models import Session, SessionSnapshot

_record_import_timing("teleclaude.core.models", _t)

_t = time.perf_counter()
from teleclaude.core.reconciliation import (
    DEFAULT_FEATURE_ID_REGISTRY,
    FleetCapabilityEntry,
    FleetCapabilityMap,
)

_record_import_timing("teleclaude.core.reconciliation", _t)

_t = time.perf_counter()
from teleclaude.core.output_poller import OutputPoller

_record_import_timing("teleclaude.core.output_poller", _t)

_t = time.perf_counter()
from teleclaude.core.reminders import ReminderService
from teleclaude.core.reminders.inbound import submit_reminder_entry

_record_import_timing("teleclaude.core.reminders", _t)

_t = time.perf_counter()
from teleclaude.core.task_registry import TaskRegistry

_record_import_timing("teleclaude.core.task_registry", _t)

_t = time.perf_counter()
from teleclaude.core.todos_db import TodosDb, set_todos_mutation_hook

_record_import_timing("teleclaude.core.todos_db", _t)

_t = time.perf_counter()
from teleclaude.daemon_event_platform import _DaemonEventPlatformMixin

_record_import_timing("teleclaude.daemon_event_platform", _t)

_t = time.perf_counter()
from teleclaude.core.hook_outbox_queue import HookOutboxSessionQueue
from teleclaude.daemon_hook_outbox import _DaemonHookOutboxMixin

_record_import_timing("teleclaude.daemon_hook_outbox", _t)

_t = time.perf_counter()
from teleclaude.daemon_session import _DaemonSessionMixin

_record_import_timing("teleclaude.daemon_session", _t)

_t = time.perf_counter()
from teleclaude.events import EventDB
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.hooks.webhook_models import HookEvent

_record_import_timing("teleclaude.events", _t)

_t = time.perf_counter()
from teleclaude.logging_config import setup_logging

_record_import_timing("teleclaude.logging_config", _t)

_t = time.perf_counter()
from teleclaude.mirrors import MirrorWorker

_record_import_timing("teleclaude.mirrors", _t)

_t = time.perf_counter()
from teleclaude.mirrors.processors import register_default_processors

_record_import_timing("teleclaude.mirrors.processors", _t)

_t = time.perf_counter()
from teleclaude.paths import MAIN_DB_PATH, PROJECT_ENV_PATH, RUNTIME_SETTINGS_PATH

_record_import_timing("teleclaude.paths", _t)

_t = time.perf_counter()
from teleclaude.services.maintenance_service import MaintenanceService

_record_import_timing("teleclaude.services.maintenance_service", _t)

_t = time.perf_counter()
from teleclaude.services.monitoring_service import MonitoringService

_record_import_timing("teleclaude.services.monitoring_service", _t)

_t = time.perf_counter()
from teleclaude.tts.manager import TTSManager

_record_import_timing("teleclaude.tts.manager", _t)

_t = time.perf_counter()
from teleclaude.transport.cluster_bridge import ClusterBridge, ClusterCategory, ClusterEnvelope
from teleclaude.transport.cluster_publisher import ClusterPublisher
from teleclaude.transport.identity_bridge import IdentityBridge, IdentityEnvelope
from teleclaude.transport.workflow_bridge import WorkflowBridge, WorkflowEnvelope

_record_import_timing("teleclaude.transport.workflow_bridge", _t)

init_voice_handler = voice_message_handler.init_voice_handler


# Logging defaults (can be overridden via environment variables)
DEFAULT_LOG_LEVEL = "INFO"
SLOW_STARTUP_WARNING_S = 30.0
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


class TeleClaudeDaemon(_DaemonHookOutboxMixin, _DaemonEventPlatformMixin, _DaemonSessionMixin):
    """Main TeleClaude daemon that coordinates all components."""

    def __init__(self, env_path: str):
        """Initialize daemon.

        Args:
            env_path: Path to .env file
        """
        # Load environment variables
        load_dotenv(env_path)
        self._httpx_runtime_debug_module = _httpx_runtime_debug

        # Log experiment status if any are enabled
        if config.experiments:
            logger.info("Loaded %d experiments from overlay", len(config.experiments))
            for exp in config.experiments:
                logger.debug("Active experiment: name=%s agents=%s", exp.name, exp.agents)

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: TextIO | None = None  # Will hold the locked file handle

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
                queue_background_task=self._queue_background_task,  # type: ignore[arg-type]
                bootstrap_session=self._bootstrap_session_resources,
            )
        )
        self.reminder_service = ReminderService(
            db,
            submitter=submit_reminder_entry,
            projection_notifier=self._schedule_reminder_projection,
        )

        # Initialize cache for remote data
        self.cache = DaemonCache(
            on_stale_read=TeleClaudeDaemon._make_stale_read_callback(
                local_computer_name=config.computer.name,
                get_adapter=lambda: self.client.transport,
            )
        )
        self.client.cache = self.cache
        logger.info("DaemonCache initialized")

        # Initialize TTS manager for direct speech (no event bus coupling)
        self.tts_manager = TTSManager()
        logger.info("TTSManager initialized")

        # Initialize ChipTunes manager for SID background music
        chiptunes_cfg = config.chiptunes
        chiptunes_music_dir = (
            Path(chiptunes_cfg.music_dir)
            if chiptunes_cfg and chiptunes_cfg.music_dir
            else project_root / "assets" / "audio" / "C64Music"
        )
        chiptunes_volume = chiptunes_cfg.volume if chiptunes_cfg else 1.0
        self.chiptunes_manager = ChiptunesManager(
            chiptunes_music_dir,
            volume=chiptunes_volume,
            default_music_dir=project_root / "assets" / "audio" / "C64Music",
            worker_lease_ttl_seconds=config.process_janitor.lease_ttl_seconds,
        )
        self.chiptunes_manager.on_track_start = self._on_chiptunes_track_start
        self.chiptunes_manager.on_state_change = self._on_chiptunes_state_change
        self.chiptunes_manager.on_command_done = self._on_chiptunes_command_done
        self.tts_manager.set_chiptunes_manager(self.chiptunes_manager)
        from teleclaude.api import chiptunes_routes  # startup boundary

        chiptunes_routes.configure(manager=self.chiptunes_manager)
        logger.info("ChiptunesManager initialized (music_dir=%s)", chiptunes_music_dir)

        # Mutable runtime settings with debounced JSON persistence
        self.runtime_settings = RuntimeSettings(RUNTIME_SETTINGS_PATH, self.tts_manager)
        # Fail closed: a replayed enabled=True on an unprovisioned/unsupported host is
        # forced off (and persisted) before the settings API can report it.
        self.runtime_settings.reconcile_tts_provisioning()

        self.maintenance_service = MaintenanceService(
            client=self.client,
            output_poller=self.output_poller,
            poller_watch_interval_s=5.0,
        )

        # Initialize AgentCoordinator for agent events and cross-computer orchestration
        self.agent_coordinator = AgentCoordinator(
            self.client,
            self.tts_manager,
            reminder_service=self.reminder_service,
        )
        session_cleanup.configure_reminder_service(self.reminder_service)
        register_default_processors()

        # Wire direct agent event handler — replaces event bus for AGENT_EVENT.
        # polling_coordinator and redis_transport call this directly instead of
        # fire-and-forget through event_bus.emit().
        self.client.agent_event_handler = self._handle_agent_event_direct
        self.client.agent_coordinator = self.agent_coordinator

        # Daemon-owned event subscriptions. AGENT_EVENT bypasses the bus —
        # it is routed directly via adapter_client.agent_event_handler above.
        # Other events (AGENT_ACTIVITY, AGENT_AVAILABILITY, SESSION_UPDATED, etc.)
        # are owned by their respective components (api_server, adapters).
        event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, self._handle_session_started)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSED, self._handle_session_closed)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSE_REQUESTED, self._handle_session_close_requested)
        event_bus.subscribe(TeleClaudeEvents.ERROR, self._handle_error)
        event_bus.subscribe("system_command", self._handle_system_command)

        # Note: Adapters are loaded in client.start(), not here

        # Shutdown event for graceful termination
        self.shutdown_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task[object]] = set()
        # Per-session outbox processing: one serial worker per session, parallel across sessions.
        self._session_outbox_queues: dict[str, HookOutboxSessionQueue] = {}
        self._session_outbox_workers: dict[str, asyncio.Task[None]] = {}
        self._hook_outbox_processed_count = 0
        self._hook_outbox_coalesced_count = 0
        self._hook_outbox_stale_dropped_count = 0
        self._hook_outbox_lag_samples_s: list[float] = []
        self._hook_outbox_last_summary_at = time.monotonic()
        self._hook_outbox_last_backlog_warn_at: dict[str, float] = {}
        self._hook_outbox_last_lag_warn_at: dict[str, float] = {}
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.resource_monitor_task: asyncio.Task[object] | None = None
        self.process_janitor_task: asyncio.Task[object] | None = None
        self.launchd_watch_task: asyncio.Task[object] | None = None
        self.config_watch_task: asyncio.Task[object] | None = None
        self._start_time = time.time()
        self._shutdown_reason: str | None = None
        self.hook_outbox_task: asyncio.Task[object] | None = None
        self._event_db: EventDB | None = None
        self.mirror_worker_task: asyncio.Task[object] | None = None
        self._event_processor_task: asyncio.Task[object] | None = None
        self._internal_event_bus_task: asyncio.Task[object] | None = None
        self.webhook_delivery_task: asyncio.Task[object] | None = None
        self.channel_subscription_worker_task: asyncio.Task[object] | None = None
        self._ingest_scheduler_task: asyncio.Task[object] | None = None
        self._task_schedule_clock_task: asyncio.Task[object] | None = None
        self._workflow_bridge_task: asyncio.Task[object] | None = None
        self._workflow_bridge: WorkflowBridge | None = None
        self._identity_bridge_task: asyncio.Task[object] | None = None
        self._identity_bridge: IdentityBridge | None = None
        self._cluster_bridge_task: asyncio.Task[object] | None = None
        self._cluster_bridge: ClusterBridge | None = None
        self._hook_dispatcher: HookDispatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self.lifecycle = DaemonLifecycle(
            client=self.client,
            cache=self.cache,
            shutdown_event=self.shutdown_event,
            task_registry=self.task_registry,
            reminder_service=self.reminder_service,
            runtime_settings=self.runtime_settings,
            log_background_task_exception=self._log_background_task_exception,
            init_voice_handler=init_voice_handler,
            event_platform_init=self._start_event_platform_prepare,
            event_consumer_start=self._start_event_consumers,
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
            db_path=str(MAIN_DB_PATH),
        )
        self.process_janitor_service = ProcessJanitorService(
            db,
            ProcessJanitorSettings(
                scan_interval_seconds=config.process_janitor.scan_interval_seconds,
                default_signature_ttl_seconds=config.process_janitor.default_signature_ttl_seconds,
                dry_run_default=config.process_janitor.dry_run_default,
                reap_revalidation_seconds=config.process_janitor.reap_revalidation_seconds,
            ),
            self.shutdown_event,
        )

    async def _schedule_reminder_projection(self, session_id: str) -> None:
        """Wake the existing coalesced projection path after a source append."""
        await polling_coordinator.schedule_session_projection(session_id, self.client)

    def _on_chiptunes_track_start(self, track_label: str, sid_path: str) -> None:
        """Broadcast chiptunes_track WebSocket event when a new track starts.

        Called from the chiptunes worker thread — bridges to the async event loop
        using call_soon_threadsafe so the broadcast runs on the event loop thread.
        """
        from teleclaude.api_models import ChiptunesTrackEventDTO  # startup boundary

        api_server = getattr(self.lifecycle, "api_server", None)
        loop = getattr(self, "_loop", None)
        logger.info(
            "ChipTunes: track_start callback fired (track=%s, api_server=%s, loop=%s, loop_running=%s)",
            track_label,
            api_server is not None,
            loop is not None,
            loop.is_running() if loop else False,
        )
        if api_server is None:
            return

        payload = ChiptunesTrackEventDTO(track=track_label, sid_path=sid_path).model_dump()
        if loop is not None and loop.is_running():
            logger.info("ChipTunes: scheduling WS broadcast (ws_clients=%d)", len(api_server._ws_clients))
            loop.call_soon_threadsafe(api_server._broadcast_payload, "chiptunes_track", payload)
            loop.call_soon_threadsafe(self._broadcast_chiptunes_state)
        else:
            logger.warning("ChipTunes: no running event loop, skipping track broadcast")

    def _on_chiptunes_state_change(
        self,
        state: ChiptunesState,
    ) -> None:
        """Broadcast chiptunes_state WebSocket events from worker thread callbacks."""
        if hasattr(self, "tts_manager"):
            self.tts_manager.on_chiptunes_state_change()
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._broadcast_chiptunes_state)
        else:
            logger.debug("ChipTunes: no running event loop, skipping state broadcast")

    def _on_chiptunes_command_done(self, command_id: str) -> None:
        """Clear pending command in routes when worker completes it."""
        from teleclaude.api import chiptunes_routes  # startup boundary

        chiptunes_routes.clear_pending(command_id)

    def _broadcast_chiptunes_state(self) -> None:
        """Broadcast the current chiptunes playback state."""
        from teleclaude.api import chiptunes_routes  # startup boundary
        from teleclaude.api_models import ChiptunesStateEventDTO  # startup boundary

        api_server = getattr(self.lifecycle, "api_server", None)
        manager = getattr(self, "chiptunes_manager", None)
        if api_server is None or manager is None:
            return

        state = manager.last_state
        track_path = str(state.get("track_path", ""))
        track_label = Path(track_path).stem.replace("_", " ") if track_path else ""
        playback = str(state.get("playback", "cold"))
        chiptunes_routes.increment_state_version()
        payload = ChiptunesStateEventDTO(
            playback=playback,  # type: ignore[arg-type]
            state_version=chiptunes_routes._state_version,
            loaded=manager.enabled,
            playing=playback == "playing",
            paused=playback == "paused",
            position_seconds=float(state.get("position_seconds", 0.0)),
            track=track_label,
            sid_path=track_path,
            pending_command_id=chiptunes_routes._pending_command_id,
            pending_action=chiptunes_routes._pending_action,  # type: ignore[arg-type]
        ).model_dump()
        api_server._broadcast_payload("chiptunes_state", payload)

    def _register_todos_mutation_hook(self) -> None:
        """Wire TodosDb mutation callbacks to daemon cache refresh.

        Called at daemon startup after the event loop is running. Every TodosDb
        instance created after this point (via get_todos_db or get_todos_db_sync)
        in teleclaude.core.todos_db
        will call refresh_local_todos on the DaemonCache whenever a mutation
        (write_state, deliver, write_artifact, etc.) is committed.
        """
        loop = self._loop
        cache = self.cache
        computer = config.computer.name

        def _hook(instance: TodosDb, project_root: str) -> None:
            async def _emit_finalize_ready(slug: str, state: Mapping[str, object]) -> None:
                finalize = state.get("finalize")
                finalize_state = finalize if isinstance(finalize, dict) else {}
                sha = str(finalize_state.get("sha", ""))
                branch = str(finalize_state.get("branch", slug))
                await emit_event(
                    event="domain.software-development.planning.todo_finalize_ready",
                    source="workflow",
                    level=EventLevel.WORKFLOW,
                    domain="software-development",
                    visibility=EventVisibility.LOCAL,
                    entity=slug,
                    description=f"Finalize ready for {slug} (sha {sha[:8] if sha else 'unknown'})",
                    payload={
                        "slug": slug,
                        "branch": branch,
                        "sha": sha,
                        "project_path": project_root,
                        "worker_session_id": str(finalize_state.get("worker_session_id", "")),
                        "ready_at": str(finalize_state.get("ready_at", "")),
                    },
                )

            async def _emit_phase_advanced(slug: str, prior_phase: str, new_phase: str) -> None:
                await emit_event(
                    event="workflow.todo.phase_advanced",
                    source="workflow",
                    level=EventLevel.WORKFLOW,
                    domain="software-development",
                    entity=slug,
                    description=f"Lifecycle phase advanced for {slug}: {prior_phase} -> {new_phase}",
                    payload={
                        "slug": slug,
                        "prior_lifecycle_phase": prior_phase,
                        "lifecycle_phase": new_phase,
                        "project_path": project_root,
                    },
                )

            async def _emit_delivered(slug: str, delivery_commit: str | None, delivered_at: str) -> None:
                await emit_event(
                    event="workflow.todo.delivered",
                    source="workflow",
                    level=EventLevel.WORKFLOW,
                    domain="software-development",
                    visibility=EventVisibility.LOCAL,
                    entity=slug,
                    description=f"Delivered {slug}",
                    payload={
                        "slug": slug,
                        "project_path": project_root,
                        "delivery_commit": delivery_commit,
                        "delivered_at": delivered_at,
                    },
                )

            def _on_mutation(event_hint: str = "todo_updated", event_data: object | None = None) -> None:
                if loop is not None and loop.is_running():
                    hint = event_hint  # capture for lambda closure
                    data = event_data if isinstance(event_data, dict) else None
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(cache.refresh_local_todos(computer, project_root, hint, data))
                    )

            def _on_phase_transition(
                slug: str,
                prior_lifecycle_phase: str,
                new_lifecycle_phase: str,
                state_payload: Mapping[str, object],
            ) -> None:
                if loop is None or not loop.is_running():
                    return
                if new_lifecycle_phase == "finalize_ready":
                    payload = dict(state_payload)
                    loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_emit_finalize_ready(slug, payload)))
                    return
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        _emit_phase_advanced(slug, prior_lifecycle_phase, new_lifecycle_phase)
                    )
                )

            def _on_delivered(slug: str, delivery_commit: str | None, delivered_at: str) -> None:
                if loop is None or not loop.is_running():
                    return
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(_emit_delivered(slug, delivery_commit, delivered_at))
                )

            instance._on_mutation = _on_mutation
            instance._on_phase_transition = _on_phase_transition
            instance._on_delivered = _on_delivered

        set_todos_mutation_hook(_hook)
        logger.info("Todos mutation hook registered (computer=%s)", computer)

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
        _message_id: str | None = None,
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
        from teleclaude.core import tmux_io  # startup boundary
        from teleclaude.core.models import MessageMetadata  # startup boundary
        from teleclaude.core.session_utils import resolve_working_dir  # startup boundary

        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.error("Session %s not found", session_id)
            return False

        command_sha = hashlib.sha256(command.encode()).hexdigest()[:12]
        logger.info(
            "execute_terminal_command",
            session_id=session_id,
            command_len=len(command),
            command_sha=command_sha,
        )
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        success = await tmux_io.process_text(
            session,
            command,
            working_dir=working_dir,
        )

        if not success:
            await self.client.send_message(session, f"Failed to execute command: {command}", metadata=MessageMetadata())
            logger.error(
                "execute_terminal_command_failed",
                session_id=session_id,
                command_len=len(command),
                command_sha=command_sha,
            )
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

        logger.info(
            "execute_terminal_command_completed",
            session_id=session_id,
            command_len=len(command),
            command_sha=command_sha,
            polling=start_polling,
        )
        return True

    async def start(self) -> None:
        """Start the daemon."""
        # Safety net: enforce single-instance lock even for direct start() callers.
        # main() already acquires this lock, so _acquire_lock() is idempotent.
        self._acquire_lock()
        self._loop = asyncio.get_running_loop()
        self._register_todos_mutation_hook()
        daemon_start_started_at = time.perf_counter()
        logger.info("Starting TeleClaude daemon...")
        logger.info("[STARTUP] Bootstrapping daemon runtime (usually 10-25s)")
        try:
            # Fold any legacy per-project/global `deployment:` block into the machine
            # config before the deployment readers (`config.deployment`) fire, then
            # reload so an existing install's channel reaches runtime rather than
            # silently falling back to the seeded default.
            from teleclaude.project_setup.init_flow import migrate_legacy_deployment_sources

            if migrate_legacy_deployment_sources(Path(WORKING_DIR)):
                reload_config()

            await self.lifecycle.startup()

            startup_elapsed = time.perf_counter() - daemon_start_started_at
            if startup_elapsed >= SLOW_STARTUP_WARNING_S:
                logger.warning("Daemon startup was slow: %.3fs", startup_elapsed)

            self._apply_chiptunes_startup_state()

            # Start periodic cleanup task (runs every hour)
            self.cleanup_task = asyncio.create_task(
                self.maintenance_service.periodic_cleanup(), name="periodic-cleanup"
            )
            self.cleanup_task.add_done_callback(self._log_background_task_exception("periodic_cleanup"))
            logger.info("Periodic cleanup task started (closed sessions purged after 7d, inbound queue trimmed at 7d)")

            # Start polling watcher (keeps pollers aligned with tmux foreground state)
            self.poller_watch_task = asyncio.create_task(
                self.maintenance_service.poller_watch_loop(), name="poller-watch"
            )
            self.poller_watch_task.add_done_callback(self._log_background_task_exception("poller_watch"))
            logger.info("Poller watch task started")

            # Watch every file the config loader reads — config.yml, the sibling
            # experiments.yml, and .env — so any edit triggers the reload decision.
            # The handler hot-reloads live sections and restarts only when a
            # connection-bound section changed.
            config_watch_paths = [config_path, config_path.parent / "experiments.yml", dotenv_path]
            self.config_watch_task = asyncio.create_task(
                ConfigWatcher(config_watch_paths, self._on_config_files_changed).run(),
                name="config-watch",
            )
            self.config_watch_task.add_done_callback(self._log_background_task_exception("config_watch"))
            logger.info("Config watcher started (config.yml + .env)")

            self.hook_outbox_task = asyncio.create_task(self._hook_outbox_worker(), name="hook-outbox-worker")
            self.hook_outbox_task.add_done_callback(self._log_background_task_exception("hook_outbox"))
            logger.info("Hook outbox worker started")

            mirror_worker = MirrorWorker()
            self.mirror_worker_task = asyncio.create_task(mirror_worker.run(), name="mirror-worker")
            self._track_background_task(self.mirror_worker_task, "mirror-worker")
            logger.info("Mirror worker started")

            # Event platform producer prep runs inside lifecycle.startup() before
            # the API server begins accepting traffic, so the producer is ready
            # by the time any /todos/* operation can be submitted. Event consumers
            # start only after the API socket is bound, so no consumer self-call
            # against that socket can land before it exists.

            # Initialize webhook service subsystem
            try:
                await self._init_webhook_service()
            except Exception:
                logger.error("Webhook service initialization failed, continuing without webhooks", exc_info=True)

            # Wire Redis transport into channels API routes
            redis_adapter = self.client.transport
            if redis_adapter is not None:
                from teleclaude.channels.api_routes import set_redis_transport  # startup boundary

                set_redis_transport(redis_adapter)

            await self._start_workflow_bridge()
            await self._start_identity_bridge()
            await self._start_cluster_bridge()

            self.resource_monitor_task = asyncio.create_task(
                self.monitoring_service.resource_monitor_loop(), name="resource-monitor"
            )
            self.resource_monitor_task.add_done_callback(self._log_background_task_exception("resource_monitor"))
            logger.info("Resource monitor started (interval=%.0fs)", RESOURCE_SNAPSHOT_INTERVAL_S)

            self.process_janitor_task = asyncio.create_task(
                self.process_janitor_service.scan_loop(), name="process-janitor"
            )
            self.process_janitor_task.add_done_callback(self._log_background_task_exception("process_janitor"))
            logger.info("Process janitor started (interval=%ss)", config.process_janitor.scan_interval_seconds)

            self._wal_checkpoint_task = asyncio.create_task(self._wal_checkpoint_loop(), name="wal-checkpoint")
            self._wal_checkpoint_task.add_done_callback(self._log_background_task_exception("wal_checkpoint"))
            logger.info("WAL checkpoint task started (interval=300s)")

            self.monitoring_service.log_resource_snapshot("startup")

            if LAUNCHD_WATCH_ENABLED:
                self.launchd_watch_task = asyncio.create_task(
                    self.monitoring_service.launchd_watch_loop(), name="launchd-watch"
                )
                self.launchd_watch_task.add_done_callback(self._log_background_task_exception("launchd_watch"))
                logger.info("Launchd watch task started (interval=%.0fs)", LAUNCHD_WATCH_INTERVAL_S)

            logger.info("TeleClaude is running. Press Ctrl+C to stop.")
        except Exception:
            # Direct start() callers may not run through main() finally.
            # Release lock on startup failure to avoid stale lock ownership.
            self._release_lock()
            raise

    def _apply_chiptunes_startup_state(self) -> None:
        """Apply chiptunes config after the event loop is running."""
        if not hasattr(self, "chiptunes_manager"):
            return
        self.chiptunes_manager.reload()
        if self.chiptunes_manager.enabled:
            self.chiptunes_manager.reattach()

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping TeleClaude daemon...")

        # Stop sandbox container (before other tasks to release socket)
        await self._stop_sandbox_manager()

        for attr_name, log_message in (
            ("cleanup_task", "Periodic cleanup task stopped"),
            ("poller_watch_task", "Poller watch task stopped"),
            ("hook_outbox_task", "Hook outbox worker stopped"),
            ("mirror_worker_task", "Mirror worker stopped"),
        ):
            await self._cancel_task_attr(attr_name, log_message)

        await self._stop_session_outbox_workers()

        workflow_bridge = getattr(self, "_workflow_bridge", None)
        if workflow_bridge is not None:
            await workflow_bridge.stop()
        await self._await_task_attr("_workflow_bridge_task", "Workflow Redis bridge stopped", timeout=5.0)

        identity_bridge = getattr(self, "_identity_bridge", None)
        if identity_bridge is not None:
            await identity_bridge.stop()
        await self._await_task_attr("_identity_bridge_task", "Identity Redis bridge stopped", timeout=5.0)

        cluster_bridge = getattr(self, "_cluster_bridge", None)
        if cluster_bridge is not None:
            await cluster_bridge.stop()
        await self._await_task_attr("_cluster_bridge_task", "Cluster Redis bridge stopped", timeout=5.0)

        await self._await_task_attr("webhook_delivery_task", "Webhook delivery worker stopped", timeout=5.0)
        await self._await_task_attr(
            "channel_subscription_worker_task",
            "Channel subscription worker stopped",
            timeout=5.0,
        )
        await self._await_task_attr("_deployment_fanout_task", "Deployment fanout stopped", timeout=5.0)
        await self._await_task_attr("_ingest_scheduler_task", "IngestScheduler stopped", timeout=5.0)
        await self._await_task_attr("_task_schedule_clock_task", "Task schedule clock stopped", timeout=5.0)
        await self._await_task_attr("_internal_event_bus_task", "Internal EventBus stopped", timeout=5.0)
        await self._await_task_attr("_event_processor_task", "EventProcessor stopped", timeout=5.0)

        for attr_name, log_message in (
            ("config_watch_task", "Config watcher stopped"),
            ("resource_monitor_task", "Resource monitor stopped"),
            ("process_janitor_task", "Process janitor stopped"),
            ("_wal_checkpoint_task", "WAL checkpoint task stopped"),
            ("launchd_watch_task", "Launchd watch task stopped"),
            ("_contract_sweep_task", "Contract sweep stopped"),
        ):
            await self._cancel_task_attr(attr_name, log_message)

        signal_ai_client = getattr(self, "_signal_ai_client", None)
        close_signal_ai = getattr(signal_ai_client, "close", None)
        if callable(close_signal_ai):
            close_result = close_signal_ai()
            if inspect.isawaitable(close_result):
                await close_result

        # Close event DB
        if self._event_db:
            await self._event_db.close()
            self._event_db = None
            logger.info("EventDB closed")

        if hasattr(self, "tts_manager"):
            await self.tts_manager.shutdown()
            logger.info("TTS manager stopped")

        # Disconnect from chiptunes worker (music keeps playing through restart)
        if hasattr(self, "chiptunes_manager"):
            self.chiptunes_manager.shutdown()
            logger.info("ChipTunes manager disconnected (worker persists)")

        # Shutdown task registry (cancel all tracked background tasks)
        if hasattr(self, "task_registry"):
            await self.task_registry.shutdown(timeout=5.0)
            logger.info("Task registry shutdown complete")

        await self.lifecycle.shutdown()

        self._release_lock()
        logger.info("Daemon stopped")

    async def _stop_sandbox_manager(self) -> None:
        """Stop the sandbox manager before other shutdown work."""
        sandbox_manager = getattr(self, "_sandbox_manager", None)
        if sandbox_manager is None:
            return
        try:
            await sandbox_manager.stop()
            logger.info("Sandbox container stopped")
        except Exception as exc:
            logger.warning("Sandbox container stop error during shutdown: %s", exc)

    async def _cancel_task_attr(self, attr_name: str, log_message: str) -> None:
        """Cancel an optional task attribute and wait for it to finish."""
        task = getattr(self, attr_name, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info(log_message)

    async def _await_task_attr(self, attr_name: str, log_message: str, *, timeout: float) -> None:
        """Await an optional task attribute without cancelling it first.

        Used for tasks that already honor shutdown_event and perform their own
        cleanup on exit. Falls back to cancellation if graceful stop times out.
        """
        task = getattr(self, attr_name, None)
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.warning("%s timed out after %.1fs; task was cancelled", attr_name, timeout)
        except asyncio.CancelledError:
            pass
        logger.info(log_message)

    async def _stop_session_outbox_workers(self) -> None:
        """Stop all per-session hook outbox workers."""
        if not self._session_outbox_workers:
            return

        workers = list(self._session_outbox_workers.values())
        self._session_outbox_workers.clear()
        self._session_outbox_queues.clear()
        self._hook_outbox_claim_paused_sessions.clear()
        for worker in workers:
            worker.cancel()
        for worker in workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        logger.info("Session outbox workers stopped (%d)", len(workers))

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

    async def _on_config_files_changed(self) -> None:
        """Apply a config.yml/.env change: hot-reload live sections, restart for the rest.

        reload_config() updates the in-memory singleton; hot-reloadable sections take
        effect immediately (tts also needs its manager to re-read). If any changed section
        is not hot-reloadable, request a graceful shutdown — launchd KeepAlive relaunches
        the daemon, which reads the fresh config at startup.
        """
        changed = reload_config()
        if not changed:
            return
        try:
            await emit_event(
                event="config.effective.updated",
                source="daemon.config_watcher",
                level=EventLevel.WORKFLOW,
                domain="config",
                payload={
                    "project_path": str(WORKING_DIR),
                    "changed_sections": sorted(changed),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        except RuntimeError:
            logger.info("config.effective.updated not emitted: event producer unavailable")
        if "tts" in changed:
            self.tts_manager.reload()
        if "chiptunes" in changed:
            self.chiptunes_manager.reload()
        restart = restart_required_sections(changed)
        if restart:
            logger.info("Config change in restart-required section(s) %s; restarting to apply", sorted(restart))
            self.request_shutdown(f"config-change:{','.join(sorted(restart))}")
        else:
            logger.info("Config hot-reloaded live: %s", sorted(changed))

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
        )

    async def _ensure_output_polling(self, session: Session) -> None:
        if await polling_coordinator.is_polling(session.session_id):
            return
        if not session.tmux_session_name or not await tmux_bridge.session_exists(
            session.tmux_session_name,
            log_missing=False,
        ):
            logger.warning("Tmux session missing for %s; polling skipped", session.session_id)
            return

        await self._poll_and_send_output(session.session_id, session.tmux_session_name)

    async def _start_polling_for_session(self, session_id: str, tmux_session_name: str) -> None:
        session = await db.get_session(session_id)
        if session:
            await self._ensure_output_polling(session)
            return
        await self._poll_and_send_output(session_id, tmux_session_name)

    async def _start_workflow_bridge(self) -> None:
        """Attach the v2 ``workflow.*`` Redis subscriber to the daemon loop.

        The bridge reuses the daemon's single ``RedisTransport`` adapter — the
        same connection pool that the rest of the daemon already authenticated
        against. No parallel client, no parallel URL/password resolution.
        """
        # startup boundary lazy imports to keep cold import cheap
        from teleclaude.transport.redis_transport import RedisTransport  # startup boundary

        redis_adapter = self.client.transport
        if not isinstance(redis_adapter, RedisTransport):
            raise RuntimeError(
                "Workflow bridge requires the v1 RedisTransport adapter to be configured before bridge startup."
            )

        def _factory() -> Any:
            return redis_adapter.redis

        bridge = WorkflowBridge(
            redis_factory=_factory,
            dispatch=self._dispatch_workflow_event,
        )
        self._workflow_bridge = bridge
        self._workflow_bridge_task = asyncio.create_task(bridge.run(), name="workflow-bridge")
        self._workflow_bridge_task.add_done_callback(self._log_background_task_exception("workflow_bridge"))
        logger.info("Workflow Redis bridge attached to shared RedisTransport")

    def _dispatch_workflow_event(self, envelope: WorkflowEnvelope) -> None:
        """Translate a decoded v2 workflow envelope into v1 cache invalidation.

        Cache invalidation drives a ``todos_updated``/``projects_updated``
        notification through the existing subscriber pipeline, which the WS
        layer fans out to connected TUIs and web clients.
        """
        category = envelope.category
        if category is None:
            return

        payload = envelope.payload
        computer_raw = payload.get("computer")
        computer = computer_raw if isinstance(computer_raw, str) and computer_raw else config.computer.name
        project_path_raw = payload.get("project_path")
        project_path = project_path_raw if isinstance(project_path_raw, str) and project_path_raw else None

        if category == "todo":
            self.cache.publish_workflow_change("todos", computer=computer, project_path=project_path)
        elif category == "artifact":
            self.cache.publish_workflow_change("artifacts", computer=computer, project_path=project_path)
        elif category == "roadmap":
            self.cache.publish_workflow_change("roadmap", computer=computer)

    async def _start_identity_bridge(self) -> None:
        """Attach the v2 ``identity.*`` Redis subscriber to the daemon loop.

        Mirrors :meth:`_start_workflow_bridge` — reuses the shared
        ``RedisTransport`` adapter rather than constructing a parallel client.
        The current v1 daemon has no identity cache that benefits from
        invalidation, so the dispatch callback logs each envelope and
        otherwise no-ops; future v1 code that needs to react to identity
        events extends the callback.
        """
        # startup boundary lazy imports to keep cold import cheap
        from teleclaude.transport.redis_transport import RedisTransport  # startup boundary

        redis_adapter = self.client.transport
        if not isinstance(redis_adapter, RedisTransport):
            raise RuntimeError(
                "Identity bridge requires the v1 RedisTransport adapter to be configured before bridge startup."
            )

        def _factory() -> Any:
            return redis_adapter.redis

        bridge = IdentityBridge(
            redis_factory=_factory,
            dispatch=self._dispatch_identity_event,
        )
        self._identity_bridge = bridge
        self._identity_bridge_task = asyncio.create_task(bridge.run(), name="identity-bridge")
        self._identity_bridge_task.add_done_callback(self._log_background_task_exception("identity_bridge"))
        logger.info("Identity Redis bridge attached to shared RedisTransport")

    def _dispatch_identity_event(self, envelope: IdentityEnvelope) -> None:
        """Log a decoded v2 identity envelope.

        The MVP dispatch is observational: there is no v1 identity cache to
        invalidate today. Extending this hook with cache invalidation is
        cheap when the need arises.
        """
        logger.info(
            "Identity v2 event observed",
            channel=envelope.channel,
            idempotency_key=envelope.idempotency_key,
            principal_kind=envelope.principal_kind,
        )

    async def _start_cluster_bridge(self) -> None:
        """Attach the cross-computer ``cluster.*`` subscriber to the daemon loop.

        Mirrors :meth:`_start_workflow_bridge` — reuses the shared
        ``RedisTransport`` adapter. The dispatch sink is currently
        observational; the next commit wires cache writes so that every
        peer's ``cluster.*`` event materializes into the local cache.
        """
        # startup boundary lazy imports to keep cold import cheap
        from teleclaude.transport.redis_transport import RedisTransport  # startup boundary

        redis_adapter = self.client.transport
        if not isinstance(redis_adapter, RedisTransport):
            raise RuntimeError(
                "Cluster bridge requires the v1 RedisTransport adapter to be configured before bridge startup."
            )

        def _factory() -> Any:
            return redis_adapter.redis

        bridge = ClusterBridge(
            redis_factory=_factory,
            dispatch=self._dispatch_cluster_event,
            registry=DEFAULT_FEATURE_ID_REGISTRY,
        )
        self._cluster_bridge = bridge
        self._cluster_bridge_task = asyncio.create_task(bridge.run(), name="cluster-bridge")
        self._cluster_bridge_task.add_done_callback(self._log_background_task_exception("cluster_bridge"))

        async def _redis_provider() -> Any:
            return await redis_adapter.get_redis()

        def _local_capability_entry() -> FleetCapabilityEntry:
            advertised_at = datetime.now(UTC)
            return FleetCapabilityEntry(
                computer=config.computer.name,
                version=__version__,
                channel=config.deployment.channel,
                capability_set=DEFAULT_FEATURE_ID_REGISTRY.carried_set(),
                last_advertised_at=advertised_at,
            )

        def _fleet_capability_map() -> FleetCapabilityMap:
            now = datetime.now(UTC)
            entries = [_local_capability_entry(), *self.cache.get_fleet_capability_entries()]
            return FleetCapabilityMap.materialize(
                entries,
                now=now,
                heartbeat_ttl_seconds=redis_adapter.heartbeat_ttl,
            )

        publisher = ClusterPublisher(
            origin=config.computer.name,
            redis_provider=_redis_provider,
            registry=DEFAULT_FEATURE_ID_REGISTRY,
            capability_map_provider=_fleet_capability_map,
        )
        self.cache.attach_cluster_publisher(publisher)
        logger.info("Cluster Redis bridge attached to shared RedisTransport")

    def _dispatch_cluster_event(self, envelope: ClusterEnvelope) -> None:
        """Materialize a cross-computer event into the local cache.

        Every daemon also receives its own ``cluster.*`` events back via Redis
        pub/sub. Self-published events are short-circuited: the local cache
        was already updated by the originating writer, and the WebSocket
        fanout fired then — re-applying here would just double-emit.

        Remote-origin events are written via cache writers with
        ``from_cluster=True`` so the dispatch path mutates state without
        re-publishing, closing the round-trip loop on peers.
        """
        if envelope.origin == config.computer.name:
            return

        category = envelope.category
        if category == ClusterCategory.SESSION:
            self._apply_session_envelope(envelope)
            return
        if category == ClusterCategory.WEBHOOK:
            self._dispatch_webhook_envelope(envelope)
            return
        if category is not None:
            # Project / todo / computer categories land in subsequent commits.
            logger.debug(
                "Cluster event ignored (category not yet wired)",
                channel=envelope.channel,
                category=category,
                origin=envelope.origin,
            )

    def _dispatch_webhook_envelope(self, envelope: ClusterEnvelope) -> None:
        """Schedule delivery of a relayed webhook event through the hook dispatcher."""
        dispatcher = self._hook_dispatcher
        if dispatcher is None:
            raise RuntimeError("Webhook cluster event received before webhook dispatcher initialized")
        event = HookEvent.from_json(json.dumps(envelope.payload))
        task = asyncio.create_task(dispatcher.dispatch(event), name="cluster-webhook-dispatch")
        task.add_done_callback(self._log_background_task_exception("cluster_webhook_dispatch"))

    def _apply_session_envelope(self, envelope: ClusterEnvelope) -> None:
        """Translate a ``cluster.session.*`` envelope into a cache mutation."""
        if envelope.channel == "cluster.session.closed":
            session_id_raw = envelope.payload.get("session_id")
            if isinstance(session_id_raw, str) and session_id_raw:
                self.cache.remove_session(session_id_raw, from_cluster=True)
            return

        try:
            snapshot = SessionSnapshot.from_dict(envelope.payload)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Discarding malformed session envelope",
                channel=envelope.channel,
                origin=envelope.origin,
                error=str(exc),
            )
            return
        self.cache.update_session(snapshot, from_cluster=True)


def _install_event_wait_tracer() -> None:
    """TEMPORARY DIAGNOSTIC: trace who creates Event.wait tasks."""
    import traceback as _tb  # startup boundary

    _original_wait = asyncio.Event.wait
    _event_wait_callers: dict[str, int] = {}

    async def _traced_wait(self: asyncio.Event) -> bool:
        task = asyncio.current_task()
        if task and task.get_name().startswith("Task-"):
            frames = _tb.format_stack(limit=10)
            # Get compact multi-line stack (skip last frame which is this tracer)
            compact_lines = []
            for f in frames[:-1]:
                for line in f.strip().split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("File"):
                        compact_lines.append(stripped[:100])
                    elif stripped.startswith("File"):
                        # Extract just filename:lineno
                        parts = stripped.split(",")
                        if len(parts) >= 2:
                            compact_lines.append(f"{parts[0].split('/')[-1].rstrip('"')}:{parts[1].strip()}")
            key = " | ".join(compact_lines[-4:])  # last 4 frames
            _event_wait_callers[key] = _event_wait_callers.get(key, 0) + 1
            total = sum(_event_wait_callers.values())
            if total % 20 == 1:
                _logger = get_logger("teleclaude.diag.event_wait")
                for k, v in sorted(_event_wait_callers.items(), key=lambda x: -x[1])[:3]:
                    _logger.warning("Event.wait top caller (x%d): %s", v, k)
        return await _original_wait(self)

    asyncio.Event.wait = _traced_wait  # type: ignore[assignment]


async def main() -> None:
    """Main entry point."""
    if os.environ.get("TELECLAUDE_TRACE_EVENT_WAIT"):
        _install_event_wait_tracer()

    # Note: .env already loaded at module import time (before config expansion)

    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    setup_logging(level=log_level)
    _emit_import_timing_logs()
    logger.info("Starting TeleClaude Daemon (version=v2-append-only-v3)")

    # Create daemon
    daemon = TeleClaudeDaemon(str(PROJECT_ENV_PATH))

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
    try:
        import uvloop  # startup boundary

        uvloop.run(main())
    except ImportError:
        asyncio.run(main())
