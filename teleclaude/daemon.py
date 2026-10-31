"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import hashlib
import logging
import os
import signal
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, TextIO

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude import __version__

_MODULE_IMPORT_STARTED_AT = time.perf_counter()
_IMPORT_TIMINGS: list[tuple[str, float, float]] = []
logger = get_logger("teleclaude.daemon")

_STOP_REASON = "stop"
_PREPARED_GRACE_EXIT_REASON = "prepared-grace-exit"
_PREPARED_EXIT_TASK_NAME = "prepared-instance-exit"
_PREPARED_EXIT_LABEL = "prepared_instance_exit"
_PREPARED_EXIT_ATTR = "prepared_exit_task"
_PREPARED_EXIT_STOPPED = "Prepared-instance exit timer stopped"
_WORKFLOW_SHUTDOWN_COMPONENT = "workflow_bridge"
_IDENTITY_SHUTDOWN_COMPONENT = "identity_bridge"
_CLUSTER_SHUTDOWN_COMPONENT = "cluster_bridge"
_EVENT_DB_SHUTDOWN_COMPONENT = "event_db"
_EVENT_REDIS_SHUTDOWN_COMPONENT = "event_platform_redis"
_TTS_SHUTDOWN_COMPONENT = "tts_manager"
_CHIPTUNES_SHUTDOWN_COMPONENT = "chiptunes_manager"
_REGISTRY_SHUTDOWN_COMPONENT = "task_registry"
_LIFECYCLE_SHUTDOWN_COMPONENT = "lifecycle"
_PREPARED_EXIT_WARNING = "No termination arrived within the grace after drained; completing own shutdown"
_IDENTITY_DECLARATION_WATCH_ATTR = "identity_declarations_watch_task"
_IDENTITY_DECLARATION_WATCH_STOPPED = "Identity declaration watcher stopped"
_IDENTITY_DECLARATION_WATCHER_STARTED = "Identity declaration watcher started"
_WORKER_TIMED_OUT = "%s timed out after %.1fs; task was cancelled"


class _Worker(StrEnum):
    """The steady-state workers the daemon service supervises, by task name."""

    CLEANUP = "periodic-cleanup"
    POLLER_WATCH = "poller-watch"
    IDLE_CYCLE = "conversation-idle-cycle"
    CONFIG_WATCH = "config-watch"
    PROJECTS_WATCH = "projects-watch"
    IDENTITY_DECLARATIONS_WATCH = "identity-declarations-watch"
    HOOK_OUTBOX = "hook-outbox-worker"
    AGENT_STATUS_WATCHDOG = "agent-status-watchdog"
    MIRROR_WORKER = "mirror-worker"
    RESOURCE_MONITOR = "resource-monitor"
    PROCESS_JANITOR = "process-janitor"
    WAL_CHECKPOINT = "wal-checkpoint"
    LAUNCHD_WATCH = "launchd-watch"
    WORKFLOW_BRIDGE = "workflow-bridge"
    IDENTITY_BRIDGE = "identity-bridge"
    CLUSTER_BRIDGE = "cluster-bridge"


if TYPE_CHECKING:
    from teleclaude.api.chiptunes_routes import TrackPreferences
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
from teleclaude.config._machine_build import WORKING_DIR
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.loader import validate_declaration_file
from teleclaude.config.machine import (
    config,
    config_path,
    machine_configuration_sources,
    reload_config,
    restart_required_sections,
)
from teleclaude.config.registered_homes import live_tier_declarations
from teleclaude.core.config_validation_reports import MACHINE_CONFIGURATION, ConfigValidationReports
from teleclaude.core.config_watcher import ConfigWatcher

_record_import_timing("teleclaude.config.machine", _t)

_t = time.perf_counter()
from teleclaude.config.runtime_settings import RuntimeSettings

_record_import_timing("teleclaude.config.runtime_settings", _t)

_t = time.perf_counter()
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, voice_message_handler
from teleclaude.core.injected_text import InjectedInputAuthority

_record_import_timing("teleclaude.core bundle", _t)

_t = time.perf_counter()
from teleclaude.core.adapter_client import AdapterClient

_record_import_timing("teleclaude.core.adapter_client", _t)

_t = time.perf_counter()
from teleclaude.core.agent_coordinator import AgentCoordinator

_record_import_timing("teleclaude.core.agent_coordinator", _t)

_t = time.perf_counter()
from teleclaude.services.agent_status_watchdog import run_agent_status_watchdog

_record_import_timing("teleclaude.services.agent_status_watchdog", _t)

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
from teleclaude.core.degradation import DegradedComponent, get_degradations

_record_import_timing("teleclaude.core.db", _t)

_t = time.perf_counter()
from teleclaude.services.process_janitor import ProcessJanitorService
from teleclaude.services.process_janitor.service import ProcessJanitorSettings

_record_import_timing("teleclaude.services.process_janitor", _t)

_t = time.perf_counter()
from teleclaude.core.events import ProjectRefreshTrigger

_record_import_timing("teleclaude.core.events", _t)

_t = time.perf_counter()
from teleclaude.core.cleanup_step import cleanup_step

_record_import_timing("teleclaude.core.cleanup_step", _t)

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
from teleclaude.core.shutdown_drain import PREPARED_TERMINATION_GRACE_SECONDS, get_shutdown_drain

_record_import_timing("teleclaude.core.shutdown_drain", _t)

_t = time.perf_counter()
from teleclaude.core.task_registry import TASK_REGISTRY_SHUTDOWN_TIMEOUT_S, SupervisedTask, TaskRegistry

_record_import_timing("teleclaude.core.task_registry", _t)

_t = time.perf_counter()
from teleclaude.core.workflow_store.store import WorkflowStore, set_workflow_store_mutation_hook

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
from teleclaude.events.consumers import ConsumerRuntime
from teleclaude.events.envelope import EventHomeMarker, EventLevel, EventVisibility, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path as _workflow_event_home
from teleclaude.events.processor import EventProcessor
from teleclaude.events.producer import publish_event
from teleclaude.events.references import ConfigurationRef, TodoRef
from teleclaude.events.schemas.sdlc import (
    TodoDelivered,
    TodoDeliveredData,
    TodoFinalizeReady,
    TodoFinalizeReadyData,
    TodoPhaseAdvanced,
    TodoPhaseAdvancedData,
)
from teleclaude.events.schemas.system import EffectiveConfigUpdated, EffectiveConfigUpdatedData
from teleclaude.events.scope import ScopedClients
from teleclaude.events.wire import LegacyFacts

_record_import_timing("teleclaude.events", _t)

_t = time.perf_counter()
from teleclaude.logging_config import setup_logging

_record_import_timing("teleclaude.logging_config", _t)

_t = time.perf_counter()
from teleclaude.mirrors.archive import threadsafe_archive_adopter
from teleclaude.mirrors.closure import threadsafe_coverage_reporter
from teleclaude.mirrors.worker import MirrorWorker

_record_import_timing("teleclaude.mirrors", _t)

_t = time.perf_counter()
from teleclaude.mirrors.processors import register_default_processors

_record_import_timing("teleclaude.mirrors.processors", _t)

_t = time.perf_counter()
from teleclaude.config.declaration_changes import (
    identity_declaration_documents,
    identity_declaration_watch_paths,
    publish_declaration_changes,
)
from teleclaude.paths import (
    DAEMON_PID_PATH,
    ENV_PATH,
    MAIN_DB_PATH,
    PROJECTS_MANIFEST_PATH,
    RUNTIME_SETTINGS_PATH,
)

_record_import_timing("teleclaude.paths", _t)

_t = time.perf_counter()
from teleclaude.core.idle_close import ConversationIdleCycle

_record_import_timing("teleclaude.core.idle_close", _t)

_t = time.perf_counter()
from teleclaude.core.runtime_readiness import RuntimeReadiness
from teleclaude.core.session_compaction import session_compaction_owner

_record_import_timing("teleclaude.core.session_compaction", _t)

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


SLOW_STARTUP_WARNING_S = 30.0
_RELAY_DELIVERY_TASK_ATTRIBUTE = "_relay_delivery_task"
_RELAY_DELIVERY_STOPPED = "Relay delivery processor stopped"
_ASSESSMENT_ANNOUNCER_TASK_ATTRIBUTE = "_assessment_announcer_task"
_ASSESSMENT_ANNOUNCER_STOPPED = "Installation assessment announcer stopped"
_SOURCE_READER_TASK_ATTRIBUTE = "_source_reader_task"
_SOURCE_READER_STOPPED = "Installation source reader stopped"
_EVENT_CONSUMER_STOPPED = "Event consumer stopped"
# Startup retry configuration
STARTUP_MAX_RETRIES = 3
STARTUP_RETRY_DELAYS = [10, 20, 40]  # Exponential backoff in seconds

# API server restart policy (centralized in lifecycle)
API_RESTART_MAX = config.daemon.api_restart_max
API_RESTART_WINDOW_S = config.daemon.api_restart_window_s
API_RESTART_BACKOFF_S = config.daemon.api_restart_backoff_s

# Resource monitoring
RESOURCE_SNAPSHOT_INTERVAL_S = config.daemon.resource_snapshot_interval_s
LAUNCHD_WATCH_INTERVAL_S = config.daemon.launchd_watch_interval_s
# The launchd probe returns at once off macOS, so it is supervised only where it runs for the daemon's lifetime.
LAUNCHD_WATCH_ENABLED = config.daemon.launchd_watch_enabled and sys.platform == "darwin"


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
        self._config_validation_reports = ConfigValidationReports()
        self._httpx_runtime_debug_module = _httpx_runtime_debug

        # Log experiment status if any are enabled
        if config.experiments:
            logger.info("Loaded %d experiments from overlay", len(config.experiments))
            for exp in config.experiments:
                logger.debug("Active experiment: name=%s agents=%s", exp.name, exp.agents)

        project_root = Path(__file__).parent.parent
        # PID file for locking - lives in the installation root, outside every release
        self.pid_file = DAEMON_PID_PATH
        self.pid_file_handle: TextIO | None = None  # Will hold the locked file handle

        # Note: tmux_bridge and db are functional modules (no instantiation)
        # UI output management is now handled by UiAdapter (base class for Telegram, Slack, etc.)
        self.output_poller = OutputPoller()

        # Initialize task registry for tracking background tasks
        self.drain = get_shutdown_drain()
        self.task_registry = TaskRegistry(drain=self.drain, escalate=self.request_shutdown)
        self.runtime_readiness = RuntimeReadiness()

        # Initialize unified adapter client (observer pattern - NO daemon reference)
        self.client = AdapterClient(
            task_registry=self.task_registry,
            runtime_readiness=self.runtime_readiness,
        )
        self.client.system_command_handler = self._handle_system_command_direct
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
        )

        # Initialize cache for remote data
        self.cache = DaemonCache()
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

        chiptunes_routes.configure(manager=self.chiptunes_manager, publish_state=self._broadcast_chiptunes_state)
        logger.info("ChiptunesManager initialized (music_dir=%s)", chiptunes_music_dir)

        # Mutable runtime settings with debounced JSON persistence
        self.runtime_settings = RuntimeSettings(RUNTIME_SETTINGS_PATH, self.tts_manager)
        # Fail closed: a replayed enabled=True on an unprovisioned/unsupported host is
        # forced off (and persisted) before the settings API can report it.
        self.runtime_settings.reconcile_tts_provisioning()

        # Inject the same persisted-attempt owner before lifecycle startup starts
        # inbound queue workers or the later poller and idle-cycle loops.
        self.maintenance_service = MaintenanceService(
            client=self.client,
            output_poller=self.output_poller,
            poller_watch_interval_s=5.0,
            task_registry=self.task_registry,
            compaction_owner=session_compaction_owner,
        )

        # Initialize AgentCoordinator for agent events and cross-computer orchestration
        self.agent_coordinator = AgentCoordinator(
            self.client,
            self.tts_manager,
            runtime_readiness=self.runtime_readiness,
            reminder_service=self.reminder_service,
            compaction_owner=session_compaction_owner,
        )
        self.runtime_readiness.set_no_composer_handler(self.agent_coordinator.handle_delivery_no_composer)
        session_cleanup.configure_reminder_service(self.reminder_service)
        register_default_processors()

        # Wire direct agent event handling at the runtime owner.
        self.client.agent_event_handler = self._handle_agent_event_direct
        self.client.agent_coordinator = self.agent_coordinator

        # Note: Adapters are loaded in client.start(), not here

        # Stop request: set when ordinary shutdown begins preparation. The shutdown event
        # that ends the daemon's consumers and loops is set only after accepted work settles.
        self.stop_requested = asyncio.Event()
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
        self.resource_monitor_task: SupervisedTask | None = None
        self.process_janitor_task: SupervisedTask | None = None
        self.launchd_watch_task: SupervisedTask | None = None
        self.config_watch_task: SupervisedTask | None = None
        self.projects_watch_task: SupervisedTask | None = None
        self.identity_declarations_watch_task: SupervisedTask | None = None
        self._start_time = time.time()
        self._shutdown_reason: str | None = None
        self.prepared_exit_task: asyncio.Task[object] | None = None
        self.hook_outbox_task: SupervisedTask | None = None
        self.agent_status_watchdog_task: SupervisedTask | None = None
        self._event_db: EventDB | None = None
        self._event_redis_client: ScopedClients[Any] | None = None
        self._fleet_capability_map_provider: Callable[[], FleetCapabilityMap] | None = None
        self.mirror_worker_task: SupervisedTask | None = None
        self._event_consumer_tasks: tuple[SupervisedTask, ...] = ()
        self._platform_consumer_runtime: ConsumerRuntime | None = None
        self._runtime_consumer_runtime: ConsumerRuntime | None = None
        self._relay_delivery_processor: EventProcessor[Any] | None = None
        self._relay_delivery_task: SupervisedTask | None = None
        self._task_schedule_clock_task: SupervisedTask | None = None
        self._assessment_announcer_task: SupervisedTask | None = None
        self._source_reader_task: SupervisedTask | None = None
        self._workflow_bridge_task: SupervisedTask | None = None
        self._workflow_bridge: WorkflowBridge | None = None
        self._identity_bridge_task: SupervisedTask | None = None
        self._identity_bridge: IdentityBridge | None = None
        self._cluster_bridge_task: SupervisedTask | None = None
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
            recover_session_startups=self._recover_session_startups,
            event_platform_init=self._start_event_platform_prepare,
            event_consumer_start=self._start_event_consumers,
            api_restart_max=API_RESTART_MAX,
            api_restart_window_s=API_RESTART_WINDOW_S,
            api_restart_backoff_s=API_RESTART_BACKOFF_S,
            escalate=self.request_shutdown,
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

    def _on_chiptunes_track_start(self, track_label: str, sid_path: str) -> None:
        """Broadcast chiptunes_track WebSocket event when a new track starts.

        Called from the chiptunes worker thread — bridges to the async event loop
        using call_soon_threadsafe so the broadcast runs on the event loop thread.
        """
        from teleclaude.api import chiptunes_routes  # startup boundary
        from teleclaude.api_models_chiptunes import ChiptunesTrackEventDTO  # startup boundary

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

        track_preferences = chiptunes_routes.track_preferences(sid_path)
        payload = ChiptunesTrackEventDTO(
            track=track_label,
            sid_path=sid_path,
            favorited=track_preferences.favorited,
            disliked=track_preferences.disliked,
        ).model_dump()
        if loop is not None and loop.is_running():
            logger.info("ChipTunes: scheduling WS broadcast (ws_clients=%d)", len(api_server._ws_clients))
            loop.call_soon_threadsafe(api_server._broadcast_payload, "chiptunes_track", payload)
            loop.call_soon_threadsafe(self._broadcast_chiptunes_state, track_preferences)
        else:
            logger.warning("ChipTunes: no running event loop, skipping track broadcast")

    def _on_chiptunes_state_change(
        self,
        state: ChiptunesState,
    ) -> None:
        """Broadcast chiptunes_state WebSocket events from worker thread callbacks."""
        from teleclaude.api import chiptunes_routes  # startup boundary

        if hasattr(self, "tts_manager"):
            self.tts_manager.on_chiptunes_state_change()
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(
                self._broadcast_chiptunes_state, chiptunes_routes.track_preferences(str(state.get("track_path", "")))
            )
        else:
            logger.debug("ChipTunes: no running event loop, skipping state broadcast")

    def _on_chiptunes_command_done(self, command_id: str) -> None:
        """Clear pending command in routes when worker completes it."""
        from teleclaude.api import chiptunes_routes  # startup boundary

        chiptunes_routes.clear_pending(command_id)

    def _broadcast_chiptunes_state(self, track_preferences: "TrackPreferences") -> None:
        """Broadcast the current chiptunes playback state, with the preference marks of its track."""
        from teleclaude.api import chiptunes_routes  # startup boundary
        from teleclaude.api_models_chiptunes import ChiptunesStateEventDTO  # startup boundary

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
            configured=chiptunes_routes.chiptunes_configured(),
            loaded=manager.enabled,
            playing=playback == "playing",
            paused=playback == "paused",
            position_seconds=float(state.get("position_seconds", 0.0)),
            track=track_label,
            sid_path=track_path,
            favorited=track_preferences.favorited,
            disliked=track_preferences.disliked,
            pending_command_id=chiptunes_routes._pending_command_id,
            pending_action=chiptunes_routes._pending_action,  # type: ignore[arg-type]
        ).model_dump()
        api_server._broadcast_payload("chiptunes_state", payload)

    def _register_todos_mutation_hook(self) -> None:
        """Wire WorkflowStore mutation callbacks to daemon cache refresh.

        Called at daemon startup after the event loop is running. Every WorkflowStore
        instance created after this point (via get_workflow_store or get_workflow_store_sync)
        in teleclaude.core.todos_db
        will call refresh_local_todos on the DaemonCache whenever a mutation
        (write_state, deliver, write_artifact, etc.) is committed.
        """
        loop = self._loop
        cache = self.cache
        computer = config.computer.name

        def _hook(instance: WorkflowStore, project_root: str) -> None:
            async def _emit_finalize_ready(slug: str, state: Mapping[str, object]) -> None:
                finalize = state.get("finalize")
                finalize_state = finalize if isinstance(finalize, dict) else {}
                sha = str(finalize_state.get("sha", ""))
                branch = str(finalize_state.get("branch", slug))
                worker_session_id = str(finalize_state.get("worker_session_id", ""))
                await publish_event(
                    TodoFinalizeReady(
                        id=occurrence_id(slug, sha, worker_session_id),
                        subject=TodoRef(slug),
                        home=_workflow_event_home(project_root),
                        data=TodoFinalizeReadyData(
                            slug=slug,
                            branch=branch,
                            sha=sha,
                            project_path=project_root,
                            worker_session_id=worker_session_id,
                            ready_at=str(finalize_state.get("ready_at", "")),
                        ),
                    ),
                    LegacyFacts(
                        producer="workflow",
                        level=EventLevel.WORKFLOW,
                        domain="sdlc",
                        visibility=EventVisibility.LOCAL,
                        entity=slug,
                        description=f"Finalize ready for {slug} (sha {sha[:8] if sha else 'unknown'})",
                    ),
                )

            async def _emit_phase_advanced(slug: str, prior_phase: str, new_phase: str) -> None:
                await publish_event(
                    TodoPhaseAdvanced(
                        subject=TodoRef(slug),
                        home=_workflow_event_home(project_root),
                        data=TodoPhaseAdvancedData(
                            slug=slug,
                            prior_lifecycle_phase=prior_phase,
                            lifecycle_phase=new_phase,
                            project_path=project_root,
                        ),
                    ),
                    LegacyFacts(
                        producer="workflow",
                        level=EventLevel.WORKFLOW,
                        domain="sdlc",
                        entity=slug,
                        description=f"Lifecycle phase advanced for {slug}: {prior_phase} -> {new_phase}",
                    ),
                )

            async def _emit_delivered(slug: str, delivery_commit: str | None, delivered_at: str) -> None:
                await publish_event(
                    TodoDelivered(
                        subject=TodoRef(slug),
                        home=_workflow_event_home(project_root),
                        data=TodoDeliveredData(
                            slug=slug,
                            project_path=project_root,
                            delivery_commit=delivery_commit,
                            delivered_at=delivered_at,
                        ),
                    ),
                    LegacyFacts(
                        producer="workflow",
                        level=EventLevel.WORKFLOW,
                        domain="sdlc",
                        visibility=EventVisibility.LOCAL,
                        entity=slug,
                        description=f"Delivered {slug}",
                    ),
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

            instance.set_workflow_hooks(_on_mutation, _on_phase_transition, _on_delivered)

        set_workflow_store_mutation_hook(_hook)
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
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
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
            authority=InjectedInputAuthority.INTERFACE,
            readiness=self.client.runtime_readiness,
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
            await self.lifecycle.startup()
            # Report every live declaration this computer cannot run on; a refusal never blocks startup.
            await self._judge_declaration_readiness(live_tier_declarations())

            startup_elapsed = time.perf_counter() - daemon_start_started_at
            if startup_elapsed >= SLOW_STARTUP_WARNING_S:
                logger.warning("Daemon startup was slow: %.3fs", startup_elapsed)

            await self._apply_chiptunes_startup_state()

            # Start periodic cleanup task (runs every hour)
            self.cleanup_task = self.task_registry.supervise(
                _Worker.CLEANUP, self.maintenance_service.periodic_cleanup, restart=True
            )
            logger.info(
                "Periodic cleanup task started (closed sessions soft-deleted after retention window, inbound queue trimmed at 7d)"
            )

            # Start polling watcher (keeps pollers aligned with tmux foreground state)
            self.poller_watch_task = self.task_registry.supervise(
                _Worker.POLLER_WATCH, self.maintenance_service.poller_watch_loop, restart=True
            )
            logger.info("Poller watch task started")

            idle_cycle = ConversationIdleCycle(self.client, session_compaction_owner)
            self.idle_cycle_task = self.task_registry.supervise(_Worker.IDLE_CYCLE, idle_cycle.run, restart=True)
            logger.info("Conversation idle cycle started")

            # Watch every file the config loader reads — config.yml, the sibling
            # experiments.yml, and .env — so any edit triggers the reload decision.
            # The handler hot-reloads live sections and restarts only when a
            # connection-bound section changed.
            config_watch_paths = machine_configuration_sources()
            config_watcher = ConfigWatcher(config_watch_paths, self._on_config_files_changed)
            self.config_watch_task = self.task_registry.supervise(
                _Worker.CONFIG_WATCH, config_watcher.run, restart=True
            )
            logger.info("Config watcher started (config.yml + .env)")

            projects_watcher = ConfigWatcher([PROJECTS_MANIFEST_PATH], self._on_projects_registry_changed)
            self.projects_watch_task = self.task_registry.supervise(
                _Worker.PROJECTS_WATCH, projects_watcher.run, restart=True
            )
            logger.info("Project registry watcher started (%s)", PROJECTS_MANIFEST_PATH)

            identity_declarations_watcher = ConfigWatcher(
                identity_declaration_watch_paths, self._on_identity_declarations_changed
            )
            self.identity_declarations_watch_task = self.task_registry.supervise(
                _Worker.IDENTITY_DECLARATIONS_WATCH, identity_declarations_watcher.run, restart=True
            )
            logger.info(_IDENTITY_DECLARATION_WATCHER_STARTED)

            self.hook_outbox_task = self.task_registry.supervise(
                _Worker.HOOK_OUTBOX, self._hook_outbox_worker, restart=True
            )
            logger.info("Hook outbox worker started")

            self.agent_status_watchdog_task = self.task_registry.supervise(
                _Worker.AGENT_STATUS_WATCHDOG,
                lambda: run_agent_status_watchdog(self.shutdown_event, self.agent_coordinator),
                restart=True,
            )
            logger.info("Agent status watchdog started")

            mirror_loop = asyncio.get_running_loop()
            mirror_worker = MirrorWorker(
                archive_adopter=threadsafe_archive_adopter(db, mirror_loop),
                coverage_reporter=threadsafe_coverage_reporter(mirror_loop),
            )
            self.mirror_worker_task = self.task_registry.supervise(
                _Worker.MIRROR_WORKER, mirror_worker.run, restart=True
            )
            logger.info("Mirror worker started")

            await self._start_workflow_bridge()
            await self._start_identity_bridge()
            await self._start_cluster_bridge()

            self.resource_monitor_task = self.task_registry.supervise(
                _Worker.RESOURCE_MONITOR, self.monitoring_service.resource_monitor_loop, restart=True
            )
            logger.info("Resource monitor started (interval=%.0fs)", RESOURCE_SNAPSHOT_INTERVAL_S)

            self.process_janitor_task = self.task_registry.supervise(
                _Worker.PROCESS_JANITOR, self.process_janitor_service.scan_loop, restart=True
            )
            logger.info("Process janitor started (interval=%ss)", config.process_janitor.scan_interval_seconds)

            self._wal_checkpoint_task = self.task_registry.supervise(
                _Worker.WAL_CHECKPOINT, self._wal_checkpoint_loop, restart=True
            )

            logger.info("WAL checkpoint task started (interval=300s)")

            self.monitoring_service.log_resource_snapshot("startup")

            if LAUNCHD_WATCH_ENABLED:
                self.launchd_watch_task = self.task_registry.supervise(
                    _Worker.LAUNCHD_WATCH, self.monitoring_service.launchd_watch_loop, restart=True
                )
                logger.info("Launchd watch task started (interval=%.0fs)", LAUNCHD_WATCH_INTERVAL_S)

            logger.info("TeleClaude is running. Press Ctrl+C to stop.")
        except Exception:
            # Direct start() callers may not run through main() finally.
            # Release lock on startup failure to avoid stale lock ownership.
            self._release_lock()
            raise

    async def _apply_chiptunes_startup_state(self) -> None:
        """Apply chiptunes config after the event loop is running, awaiting the registry writes off-loop.

        Chiptunes is optional: a failure here degrades it and startup continues without music.
        """
        if not hasattr(self, "chiptunes_manager"):
            return
        try:
            await self.chiptunes_manager.reload()
            if self.chiptunes_manager.enabled:
                await self.chiptunes_manager.reattach()
        except Exception as exc:
            logger.error("Chiptunes startup failed; the daemon continues without it", exc_info=True)
            get_degradations().mark(DegradedComponent.CHIPTUNES, str(exc))

    async def _settle_accepted_work(self) -> None:
        """Close admission and wait, within the preparation window, for accepted work to settle.

        Every completion dependency (hooks, readiness, storage, terminal ownership, outcome
        delivery) keeps running meanwhile. An overrun is reported and leaves the unfinished
        unit untouched; teardown then proceeds and abrupt-loss recovery owns what remains.
        """
        self.drain.begin_preparation(self._shutdown_reason or _STOP_REASON)
        if not await self.drain.wait_settled():
            logger.warning("Accepted work still unsettled at the end of the preparation window; tearing down")

    async def stop(self) -> None:
        """Stop the daemon: settle accepted work first, then tear down consumers, transports and storage."""
        logger.info("Stopping TeleClaude daemon...")
        await self._cancel_task_attr(_PREPARED_EXIT_ATTR, _PREPARED_EXIT_STOPPED)
        await self._settle_accepted_work()
        self.drain.begin_stopping()
        self.runtime_readiness.close()
        self.shutdown_event.set()

        # Stop sandbox container (before other tasks to release socket)
        await self._stop_sandbox_manager()

        for attr_name, log_message in (
            ("cleanup_task", "Periodic cleanup task stopped"),
            ("poller_watch_task", "Poller watch task stopped"),
            ("idle_cycle_task", "Conversation idle cycle stopped"),
            ("hook_outbox_task", "Hook outbox worker stopped"),
            ("agent_status_watchdog_task", "Agent status watchdog stopped"),
            ("mirror_worker_task", "Mirror worker stopped"),
        ):
            await self._stop_worker_attr(attr_name, log_message)

        await self._stop_session_outbox_workers()

        workflow_bridge = getattr(self, "_workflow_bridge", None)
        if workflow_bridge is not None:
            with cleanup_step(_WORKFLOW_SHUTDOWN_COMPONENT):
                await workflow_bridge.stop()
        await self._await_worker_attr("_workflow_bridge_task", "Workflow Redis bridge stopped", timeout=5.0)

        identity_bridge = getattr(self, "_identity_bridge", None)
        if identity_bridge is not None:
            with cleanup_step(_IDENTITY_SHUTDOWN_COMPONENT):
                await identity_bridge.stop()
        await self._await_worker_attr("_identity_bridge_task", "Identity Redis bridge stopped", timeout=5.0)

        cluster_bridge = getattr(self, "_cluster_bridge", None)
        if cluster_bridge is not None:
            with cleanup_step(_CLUSTER_SHUTDOWN_COMPONENT):
                await cluster_bridge.stop()
        await self._await_worker_attr("_cluster_bridge_task", "Cluster Redis bridge stopped", timeout=5.0)

        await self._await_worker_attr("_task_schedule_clock_task", "Task schedule clock stopped", timeout=5.0)
        await self._await_worker_attr(_ASSESSMENT_ANNOUNCER_TASK_ATTRIBUTE, _ASSESSMENT_ANNOUNCER_STOPPED, timeout=5.0)
        await self._await_worker_attr(_SOURCE_READER_TASK_ATTRIBUTE, _SOURCE_READER_STOPPED, timeout=5.0)
        for consumer_task in self._event_consumer_tasks:
            await self._await_worker(consumer_task, consumer_task.name, _EVENT_CONSUMER_STOPPED, timeout=5.0)
        await self._await_worker_attr(_RELAY_DELIVERY_TASK_ATTRIBUTE, _RELAY_DELIVERY_STOPPED, timeout=5.0)

        for attr_name, log_message in (
            ("config_watch_task", "Config watcher stopped"),
            ("projects_watch_task", "Project registry watcher stopped"),
            (_IDENTITY_DECLARATION_WATCH_ATTR, _IDENTITY_DECLARATION_WATCH_STOPPED),
            ("resource_monitor_task", "Resource monitor stopped"),
            ("process_janitor_task", "Process janitor stopped"),
            ("_wal_checkpoint_task", "WAL checkpoint task stopped"),
            ("launchd_watch_task", "Launchd watch task stopped"),
        ):
            await self._stop_worker_attr(attr_name, log_message)

        if hasattr(self, "tts_manager"):
            with cleanup_step(_TTS_SHUTDOWN_COMPONENT):
                await self.tts_manager.shutdown()
                logger.info("TTS manager stopped")

        # Disconnect from chiptunes worker (music keeps playing through restart)
        if hasattr(self, "chiptunes_manager"):
            with cleanup_step(_CHIPTUNES_SHUTDOWN_COMPONENT):
                self.chiptunes_manager.shutdown()
                logger.info("ChipTunes manager disconnected (worker persists)")

        # Shutdown task registry (cancel all tracked background tasks)
        if hasattr(self, "task_registry"):
            with cleanup_step(_REGISTRY_SHUTDOWN_COMPONENT):
                await self.task_registry.shutdown(timeout=TASK_REGISTRY_SHUTDOWN_TIMEOUT_S)
                logger.info("Task registry shutdown complete")

        with cleanup_step(_LIFECYCLE_SHUTDOWN_COMPONENT):
            await self.lifecycle.shutdown()

        # Event dependencies outlive every reader, adapter, request and runtime-owned metadata task.
        if self._event_db:
            with cleanup_step(_EVENT_DB_SHUTDOWN_COMPONENT):
                await self._event_db.close()
                self._event_db = None
                logger.info("EventDB closed")
        with cleanup_step(_EVENT_REDIS_SHUTDOWN_COMPONENT):
            await self._close_event_platform_redis()

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
            logger.warning("Sandbox container stop error during shutdown: %s", exc, exc_info=True)

    async def _cancel_task_attr(self, attr_name: str, log_message: str) -> None:
        """Cancel an optional task attribute and wait for it to finish."""
        task = getattr(self, attr_name, None)
        if task is None:
            return
        with cleanup_step(attr_name):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(log_message)

    async def _stop_worker_attr(self, attr_name: str, log_message: str) -> None:
        """Stop an optional supervised worker, cancelling it and waiting for it to end."""
        worker = getattr(self, attr_name, None)
        if worker is None:
            return
        with cleanup_step(attr_name):
            await worker.cancel()
            logger.info(log_message)

    async def _await_worker_attr(self, attr_name: str, log_message: str, *, timeout: float) -> None:
        """Stop an optional supervised worker that honors shutdown_event, then wait for it to end by itself.

        Used for workers that perform their own cleanup on exit. Falls back to
        cancellation if the graceful stop times out.
        """
        await self._await_worker(getattr(self, attr_name, None), attr_name, log_message, timeout=timeout)

    async def _await_worker(
        self, worker: SupervisedTask | None, label: str, log_message: str, *, timeout: float
    ) -> None:
        """Stop a supervised worker that honors shutdown_event, then wait for it to end by itself.

        Falls back to cancellation if the graceful stop times out.
        """
        if worker is None:
            return
        with cleanup_step(label):
            if not await worker.wait(timeout=timeout):
                logger.warning(_WORKER_TIMED_OUT, label, timeout)
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
            with cleanup_step(worker.get_name()):
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
        logger.info("Session outbox workers stopped (%d)", len(workers))

    def request_shutdown(self, reason: str) -> None:
        """Request graceful shutdown: close admission, then let the stop sequence drain and tear down."""
        self._shutdown_reason = reason
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._begin_stop(reason)
            return

        loop.call_soon_threadsafe(self._begin_stop, reason)

    def request_preparation(self, reason: str) -> None:
        """Close admission and settle accepted work, then complete this instance's own shutdown after the grace.

        The host's termination inside the grace yields the ordinary stop; without one the daemon
        requests its own shutdown, so a prepared instance never stays alive and closed.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.call_soon_threadsafe(self._begin_preparation_only, reason)

    def _begin_preparation_only(self, reason: str) -> None:
        self.drain.begin_preparation(reason)
        settle_task = self.drain.start_settling()
        if self.prepared_exit_task is not None:
            return
        self.prepared_exit_task = asyncio.create_task(
            self._complete_own_shutdown(settle_task), name=_PREPARED_EXIT_TASK_NAME
        )
        self.prepared_exit_task.add_done_callback(self._log_background_task_exception(_PREPARED_EXIT_LABEL))

    async def _complete_own_shutdown(self, settle_task: asyncio.Task[None]) -> None:
        """Request this instance's shutdown once the grace after `drained` passes without a termination.

        The grace starts only when accepted work has settled, so unsettled work is never forced.
        """
        await asyncio.shield(settle_task)
        await asyncio.sleep(PREPARED_TERMINATION_GRACE_SECONDS)
        if self.stop_requested.is_set():
            return
        logger.warning(
            _PREPARED_EXIT_WARNING,
            grace_seconds=PREPARED_TERMINATION_GRACE_SECONDS,
        )
        self.request_shutdown(_PREPARED_GRACE_EXIT_REASON)

    def _begin_stop(self, reason: str) -> None:
        """Close admission to new business work and wake the main loop into the stop sequence."""
        self.drain.begin_preparation(reason)
        self.stop_requested.set()
        self.monitoring_service.log_resource_snapshot(f"shutdown:{reason}")

    async def _on_projects_registry_changed(self) -> None:
        """Refresh the local project cache after an external registry edit."""
        await self.lifecycle.refresh_local_projects(ProjectRefreshTrigger.REGISTRY_CHANGE)

    async def _judge_declaration_readiness(self, documents: Iterable[Path]) -> None:
        """Judge each live declaration's readiness on this computer and report every change of verdict."""
        for document in documents:
            try:
                await asyncio.to_thread(validate_declaration_file, document)
            except ConfigLoadError as error:
                await self._config_validation_reports.refused(str(document), document, error)
                continue
            await self._config_validation_reports.accepted(str(document), document)

    async def _on_identity_declarations_changed(self) -> None:
        """Judge the changed declarations, then refresh config-owned project facts and invalidate identity reach."""
        await self._judge_declaration_readiness(identity_declaration_documents())
        await self.lifecycle.refresh_local_projects(ProjectRefreshTrigger.REGISTRY_CHANGE)
        publish_declaration_changes()

    async def _on_config_files_changed(self) -> None:
        """Apply a config.yml/.env change: hot-reload live sections, restart for the rest.

        reload_config() updates the in-memory singleton; hot-reloadable sections take
        effect immediately (tts also needs its manager to re-read). If any changed section
        is not hot-reloadable, request a graceful shutdown — the service manager relaunches
        the daemon after a clean exit it did not itself request, and the daemon reads the
        fresh config at startup.
        """
        try:
            changed = reload_config()
        except ConfigLoadError as error:
            # The running configuration stays in force; restart and start refuse this file too.
            await self._config_validation_reports.refused(MACHINE_CONFIGURATION, config_path, error)
            return
        await self._config_validation_reports.accepted(MACHINE_CONFIGURATION, config_path)
        if not changed:
            return
        try:
            await publish_event(
                EffectiveConfigUpdated(
                    subject=ConfigurationRef(MACHINE_CONFIGURATION),
                    home=EventHomeMarker.NONE,
                    data=EffectiveConfigUpdatedData(
                        project_path=str(WORKING_DIR),
                        changed_sections=sorted(changed),
                        updated_at=datetime.now(UTC).isoformat(),
                    ),
                ),
                LegacyFacts(producer="daemon.config_watcher", level=EventLevel.WORKFLOW, domain="config"),
            )
        except RuntimeError:
            logger.info("teleclaude.config.effective.updated not emitted: event producer unavailable")
        if "tts" in changed:
            self.tts_manager.reload()
        if "chiptunes" in changed:
            await self.chiptunes_manager.reload()
            get_degradations().clear(DegradedComponent.CHIPTUNES)
            from teleclaude.api import chiptunes_routes  # startup boundary

            self._broadcast_chiptunes_state(await asyncio.to_thread(chiptunes_routes.current_track_preferences))
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
        self._workflow_bridge_task = self.task_registry.supervise(_Worker.WORKFLOW_BRIDGE, bridge.run, restart=True)
        logger.info("Workflow Redis bridge attached to shared RedisTransport")

    def _dispatch_workflow_event(self, envelope: WorkflowEnvelope) -> None:
        """Translate a decoded v2 workflow envelope into v1 cache invalidation.

        Cache invalidation drives a ``todos_updated``/``projects_updated``
        notification through the existing subscriber pipeline, which the WS
        layer fans out to connected TUIs.
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
        self._identity_bridge_task = self.task_registry.supervise(_Worker.IDENTITY_BRIDGE, bridge.run, restart=True)
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
        self._cluster_bridge_task = self.task_registry.supervise(_Worker.CLUSTER_BRIDGE, bridge.run, restart=True)

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

        self._fleet_capability_map_provider = _fleet_capability_map
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
        if category is not None:
            # Project / todo / computer categories land in subsequent commits.
            logger.debug(
                "Cluster event ignored (category not yet wired)",
                channel=envelope.channel,
                category=category,
                origin=envelope.origin,
            )

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
    if os.environ.get("TELECLAUDE_TRACE_EVENT_WAIT"):  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        _install_event_wait_tracer()

    # Note: .env already loaded at module import time (before config expansion)

    log_level = config.daemon.log_level
    setup_logging(level=log_level)
    _emit_import_timing_logs()
    logger.info("Starting TeleClaude Daemon (version=v2-append-only-v3)")

    # Create daemon
    daemon = TeleClaudeDaemon(str(ENV_PATH))

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum: int, _frame: object) -> None:
        """Handle termination signals."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s signal...", sig_name)
        daemon.request_shutdown(sig_name)

    def preparation_signal_handler(signum: int, _frame: object) -> None:
        """Handle the host's preparation request: drain accepted work without stopping."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s signal; preparing for shutdown", sig_name)
        daemon.request_preparation(sig_name)

    # Register signal handlers (preparation first, so support is never advertised without its signal)
    signal.signal(signal.SIGUSR1, preparation_signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    exit_status = 0
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
                    exit_status = 1
                    return

                # Last attempt exhausted
                if attempt == STARTUP_MAX_RETRIES - 1:
                    logger.error(
                        "Daemon startup failed after %d attempts: %s",
                        STARTUP_MAX_RETRIES,
                        e,
                        exc_info=True,
                    )
                    exit_status = 1
                    return

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

        # Wait for a stop request; the stop sequence settles accepted work before teardown
        await daemon.stop_requested.wait()

    except DaemonLockError as e:
        logger.error(str(e))
        exit_status = 1
    except KeyboardInterrupt:
        logger.info("Received interrupt signal...")
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        exit_status = 1
    finally:
        try:
            await daemon.stop()
        except Exception as e:
            logger.error("Error during daemon stop: %s", e)
        finally:
            daemon._release_lock()
            if exit_status:
                _end_failed_process(exit_status)


def _end_failed_process(exit_status: int) -> NoReturn:
    """End a daemon that failed fatally, once its stop has run, so its service manager sees the exit.

    An ordinary interpreter exit waits for every worker thread, and one blocked thread would keep a
    daemon without its request surface alive indefinitely, invisible to the service manager.
    """
    logger.error("Daemon exiting with status %d after a fatal failure", exit_status)
    logging.shutdown()
    os._exit(exit_status)


if __name__ == "__main__":
    try:
        import uvloop  # startup boundary

        uvloop.run(main())
    except ImportError:
        asyncio.run(main())
