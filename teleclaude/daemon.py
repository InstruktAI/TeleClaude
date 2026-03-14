"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import os
import signal
import sys
import time
from pathlib import Path
from typing import TextIO, cast

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude.chiptunes.manager import ChiptunesManager
from teleclaude.config import config  # config.py loads .env at import time
from teleclaude.config.runtime_settings import RuntimeSettings
from teleclaude.core import polling_coordinator, tmux_bridge, voice_message_handler
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.cache import DaemonCache
from teleclaude.core.command_registry import init_command_service
from teleclaude.core.command_service import CommandService
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    EventType,
    TeleClaudeEvents,
)
from teleclaude.core.lifecycle import DaemonLifecycle
from teleclaude.core.models import Session
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todo_watcher import TodoWatcher
from teleclaude.daemon_event_platform import _DaemonEventPlatformMixin
from teleclaude.daemon_hook_outbox import (
    _DaemonHookOutboxMixin,
    _HookOutboxSessionQueue,
)
from teleclaude.daemon_session import _DaemonSessionMixin
from teleclaude.events import EventDB
from teleclaude.logging_config import setup_logging
from teleclaude.mirrors import MirrorWorker
from teleclaude.mirrors.processors import register_default_processors
from teleclaude.paths import RUNTIME_SETTINGS_PATH
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.services.maintenance_service import MaintenanceService
from teleclaude.services.monitoring_service import MonitoringService
from teleclaude.tts.manager import TTSManager

init_voice_handler = voice_message_handler.init_voice_handler


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


class TeleClaudeDaemon(_DaemonHookOutboxMixin, _DaemonEventPlatformMixin, _DaemonSessionMixin):  # pylint: disable=too-many-instance-attributes  # Daemon coordinator needs multiple components
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
                execute_auto_command=self._execute_auto_command,
                queue_background_task=self._queue_background_task,  # type: ignore[arg-type]
                bootstrap_session=self._bootstrap_session_resources,
            )
        )

        # Initialize cache for remote data
        self.cache = DaemonCache(
            on_stale_read=TeleClaudeDaemon._make_stale_read_callback(
                local_computer_name=config.computer.name,
                get_adapter=lambda: self.client.adapters.get("redis"),
            )
        )
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
        chiptunes_volume = chiptunes_cfg.volume if chiptunes_cfg else 0.5
        self.chiptunes_manager = ChiptunesManager(chiptunes_music_dir, volume=chiptunes_volume)
        self.chiptunes_manager.on_track_start = self._on_chiptunes_track_start
        self.chiptunes_manager.on_state_change = self._on_chiptunes_state_change
        self.tts_manager.set_chiptunes_manager(self.chiptunes_manager)
        logger.info("ChiptunesManager initialized (music_dir=%s)", chiptunes_music_dir)

        # Mutable runtime settings with debounced JSON persistence
        self.runtime_settings = RuntimeSettings(RUNTIME_SETTINGS_PATH, self.tts_manager, self.chiptunes_manager)
        self.runtime_settings.bootstrap_chiptunes()

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
        register_default_processors()

        # Wire direct agent event handler — replaces event bus for AGENT_EVENT.
        # polling_coordinator and redis_transport call this directly instead of
        # fire-and-forget through event_bus.emit().
        self.client.agent_event_handler = self._handle_agent_event_direct
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
        event_bus.subscribe("system_command", self._handle_system_command)  # type: ignore[arg-type]

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
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.resource_monitor_task: asyncio.Task[object] | None = None
        self.launchd_watch_task: asyncio.Task[object] | None = None
        self._start_time = time.time()
        self._shutdown_reason: str | None = None
        self.hook_outbox_task: asyncio.Task[object] | None = None
        self._event_db: EventDB | None = None
        self.mirror_worker_task: asyncio.Task[object] | None = None
        self._event_processor_task: asyncio.Task[object] | None = None
        self.todo_watcher_task: asyncio.Task[object] | None = None
        self.codex_transcript_watch_task: asyncio.Task[object] | None = None
        self.webhook_delivery_task: asyncio.Task[object] | None = None
        self.channel_subscription_worker_task: asyncio.Task[object] | None = None
        self._ingest_scheduler_task: asyncio.Task[object] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

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

    def _on_chiptunes_track_start(self, track_label: str, sid_path: str) -> None:
        """Broadcast chiptunes_track WebSocket event when a new track starts.

        Called from the chiptunes worker thread — bridges to the async event loop
        using call_soon_threadsafe so the broadcast runs on the event loop thread.
        """
        from teleclaude.api_models import ChiptunesTrackEventDTO

        api_server = getattr(self.lifecycle, "api_server", None)
        if api_server is None:
            return

        payload = ChiptunesTrackEventDTO(track=track_label, sid_path=sid_path).model_dump()
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(api_server._broadcast_payload, "chiptunes_track", payload)
            loop.call_soon_threadsafe(self._broadcast_chiptunes_state)
        else:
            logger.debug("ChipTunes: no running event loop, skipping track broadcast")

    def _on_chiptunes_state_change(self) -> None:
        """Broadcast chiptunes_state WebSocket events from worker thread callbacks."""
        if hasattr(self, "tts_manager"):
            self.tts_manager.on_chiptunes_state_change()
        if hasattr(self, "runtime_settings"):
            self.runtime_settings.sync_chiptunes_state()
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._broadcast_chiptunes_state)
        else:
            logger.debug("ChipTunes: no running event loop, skipping state broadcast")

    def _broadcast_chiptunes_state(self) -> None:
        """Broadcast the current chiptunes playback state."""
        from teleclaude.api_models import ChiptunesStateEventDTO

        api_server = getattr(self.lifecycle, "api_server", None)
        manager = getattr(self, "chiptunes_manager", None)
        if api_server is None or manager is None:
            return

        runtime_state = manager.capture_runtime_state()
        state_version = 0
        runtime_settings = getattr(self, "runtime_settings", None)
        if runtime_settings is not None:
            state_version = runtime_settings.chiptunes_state_version
        payload = ChiptunesStateEventDTO(
            playback=runtime_state.playback,
            state_version=state_version,
            loaded=manager.enabled,
            playing=manager.is_playing,
            paused=manager.is_paused,
            position_seconds=runtime_state.position_seconds,
            track=manager.current_track,
            sid_path=manager.current_sid_path,
            pending_command_id=runtime_state.pending_command_id,
            pending_action=runtime_state.pending_action,
        ).model_dump()
        api_server._broadcast_payload("chiptunes_state", payload)

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
        from teleclaude.core import tmux_io
        from teleclaude.core.models import MessageMetadata
        from teleclaude.core.session_utils import resolve_working_dir

        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.error("Session %s not found", session_id)
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
            logger.error("Failed to execute command in session %s: %s", session_id, command)
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

        logger.info("Executed command in session %s: %s (polling=%s)", session_id, command, start_polling)
        return True

    async def start(self) -> None:
        """Start the daemon."""
        # Safety net: enforce single-instance lock even for direct start() callers.
        # main() already acquires this lock, so _acquire_lock() is idempotent.
        self._acquire_lock()
        self._loop = asyncio.get_running_loop()
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

            mirror_db_path = getattr(getattr(config, "database", None), "path", None)
            if isinstance(mirror_db_path, str) and mirror_db_path:
                mirror_worker = MirrorWorker(mirror_db_path)
                self.mirror_worker_task = asyncio.create_task(mirror_worker.run())
                self._track_background_task(self.mirror_worker_task, "mirror-worker")
                logger.info("Mirror worker started")
            else:
                logger.warning("Mirror worker skipped: database path unavailable")

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

            # Initialize event platform
            await self._start_event_platform()

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

        # Stop sandbox container (before other tasks to release socket)
        await self._stop_sandbox_manager()

        for attr_name, log_message in (
            ("cleanup_task", "Periodic cleanup task stopped"),
            ("poller_watch_task", "Poller watch task stopped"),
            ("hook_outbox_task", "Hook outbox worker stopped"),
            ("mirror_worker_task", "Mirror worker stopped"),
            ("codex_transcript_watch_task", "Codex transcript watch task stopped"),
        ):
            await self._cancel_task_attr(attr_name, log_message)

        await self._stop_session_outbox_workers()

        for attr_name, log_message in (
            ("webhook_delivery_task", "Webhook delivery worker stopped"),
            ("channel_subscription_worker_task", "Channel subscription worker stopped"),
            ("resource_monitor_task", "Resource monitor stopped"),
            ("_wal_checkpoint_task", "WAL checkpoint task stopped"),
            ("todo_watcher_task", "Todo watcher task stopped"),
            ("launchd_watch_task", "Launchd watch task stopped"),
            ("_ingest_scheduler_task", "IngestScheduler stopped"),
            ("_event_processor_task", "EventProcessor stopped"),
        ):
            await self._cancel_task_attr(attr_name, log_message)

        if hasattr(self, "_webhook_delivery_worker"):
            await self._webhook_delivery_worker.close()

        # Close event DB
        if self._event_db:
            await self._event_db.close()
            self._event_db = None
            logger.info("EventDB closed")

        if hasattr(self, "tts_manager"):
            await self.tts_manager.shutdown()
            logger.info("TTS manager stopped")

        # Stop chiptunes playback
        if hasattr(self, "chiptunes_manager"):
            self.chiptunes_manager.stop()
            logger.info("ChipTunes manager stopped")

        # Shutdown task registry (cancel all tracked background tasks)
        if hasattr(self, "task_registry"):
            await self.task_registry.shutdown(timeout=5.0)
            logger.info("Task registry shutdown complete")

        await self.lifecycle.shutdown()

        self._release_lock()
        logger.info("Daemon stopped")

    async def _stop_sandbox_manager(self) -> None:
        """Stop the sandbox manager before other shutdown work."""
        if not hasattr(self, "_sandbox_manager"):
            return
        try:
            await self._sandbox_manager.stop()
            logger.info("Sandbox container stopped")
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
    try:
        import uvloop

        uvloop.run(main())
    except ImportError:
        asyncio.run(main())
