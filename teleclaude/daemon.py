"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import hashlib
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Coroutine, Optional, TextIO, TypedDict, cast

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config  # config.py loads .env at import time
from teleclaude.constants import MCP_SOCKET_PATH, UI_MESSAGE_MAX_CHARS
from teleclaude.core import (
    command_handlers,
    polling_coordinator,
    session_cleanup,
    terminal_bridge,
    terminal_io,
    voice_message_handler,
)
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_watcher import CodexWatcher
from teleclaude.core.db import db
from teleclaude.core.events import (
    COMMAND_EVENTS,
    AgentEventContext,
    AgentHookEvents,
    AgentStopPayload,
    CommandEventContext,
    DeployArgs,
    ErrorEventContext,
    EventContext,
    EventType,
    FileEventContext,
    MessageEventContext,
    SessionLifecycleContext,
    SystemCommandContext,
    TeleClaudeEvents,
    VoiceEventContext,
    parse_command_string,
)
from teleclaude.core.file_handler import handle_file
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_utils import get_output_file, parse_session_title
from teleclaude.core.summarizer import summarize
from teleclaude.core.terminal_events import TerminalOutboxMetadata, TerminalOutboxPayload, TerminalOutboxResponse
from teleclaude.core.voice_message_handler import init_voice_handler
from teleclaude.logging_config import setup_logging
from teleclaude.mcp_server import TeleClaudeMCPServer
from teleclaude.utils.transcript import parse_session_transcript


# TypedDict definitions for deployment status payloads
class DeployStatusPayload(TypedDict):
    """Deployment status payload - sent to Redis during deployment lifecycle."""

    status: str
    timestamp: float


class DeployErrorPayload(TypedDict):
    """Deployment error payload - sent to Redis when deployment fails."""

    status: str
    error: str


class OutputChangeSummary(TypedDict, total=False):
    """Summary details for tmux output changes."""

    changed: bool
    reason: str
    before_len: int
    after_len: int
    diff_index: int
    before_snippet: str
    after_snippet: str


# Logging defaults (can be overridden via environment variables)
DEFAULT_LOG_LEVEL = "INFO"

# Startup retry configuration
STARTUP_MAX_RETRIES = 3
STARTUP_RETRY_DELAYS = [10, 20, 40]  # Exponential backoff in seconds

# MCP server health monitoring
MCP_WATCH_INTERVAL_S = float(os.getenv("MCP_WATCH_INTERVAL_S", "2"))
MCP_WATCH_FAILURE_THRESHOLD = int(os.getenv("MCP_WATCH_FAILURE_THRESHOLD", "3"))
MCP_WATCH_RESTART_MAX = int(os.getenv("MCP_WATCH_RESTART_MAX", "3"))
MCP_WATCH_RESTART_WINDOW_S = float(os.getenv("MCP_WATCH_RESTART_WINDOW_S", "60"))
MCP_WATCH_RESTART_TIMEOUT_S = float(os.getenv("MCP_WATCH_RESTART_TIMEOUT_S", "2"))
MCP_SOCKET_HEALTH_TIMEOUT_S = float(os.getenv("MCP_SOCKET_HEALTH_TIMEOUT_S", "0.5"))
MCP_SOCKET_HEALTH_PROBE_INTERVAL_S = float(os.getenv("MCP_SOCKET_HEALTH_PROBE_INTERVAL_S", "10"))
MCP_SOCKET_HEALTH_ACCEPT_GRACE_S = float(os.getenv("MCP_SOCKET_HEALTH_ACCEPT_GRACE_S", "5"))
MCP_SOCKET_HEALTH_STARTUP_GRACE_S = float(os.getenv("MCP_SOCKET_HEALTH_STARTUP_GRACE_S", "5"))

# Hook outbox worker
HOOK_OUTBOX_POLL_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_POLL_INTERVAL_S", "1"))
HOOK_OUTBOX_BATCH_SIZE: int = int(os.getenv("HOOK_OUTBOX_BATCH_SIZE", "25"))
HOOK_OUTBOX_LOCK_TTL_S: float = float(os.getenv("HOOK_OUTBOX_LOCK_TTL_S", "30"))
HOOK_OUTBOX_BASE_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_BASE_BACKOFF_S", "1"))
HOOK_OUTBOX_MAX_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_MAX_BACKOFF_S", "60"))

# Terminal outbox worker (telec)
TERMINAL_OUTBOX_POLL_INTERVAL_S: float = float(os.getenv("TERMINAL_OUTBOX_POLL_INTERVAL_S", "0.5"))
TERMINAL_OUTBOX_BATCH_SIZE: int = int(os.getenv("TERMINAL_OUTBOX_BATCH_SIZE", "25"))
TERMINAL_OUTBOX_LOCK_TTL_S: float = float(os.getenv("TERMINAL_OUTBOX_LOCK_TTL_S", "30"))
TERMINAL_OUTBOX_BASE_BACKOFF_S: float = float(os.getenv("TERMINAL_OUTBOX_BASE_BACKOFF_S", "1"))
TERMINAL_OUTBOX_MAX_BACKOFF_S: float = float(os.getenv("TERMINAL_OUTBOX_MAX_BACKOFF_S", "60"))

# Agent auto-command startup detection
AGENT_START_TIMEOUT_S = 5.0
AGENT_START_POLL_INTERVAL_S = 0.5
AGENT_START_SETTLE_DELAY_S = 0.5  # Initial delay after process starts
AGENT_START_CONFIRM_ENTER_DELAY_S = 1.0
AGENT_START_CONFIRM_ENTER_ATTEMPTS = 4
AGENT_START_OUTPUT_TAIL_CHARS = 4000
AGENT_START_OUTPUT_POLL_INTERVAL_S = 0.2
AGENT_START_OUTPUT_CHANGE_TIMEOUT_S = 2.5
AGENT_START_ENTER_INTER_DELAY_S = 0.2
AGENT_START_POST_INJECT_DELAY_S = 1.0
AGENT_START_STABILIZE_TIMEOUT_S = 15.0  # Max wait for output to stop changing (MCP loading)
AGENT_START_STABILIZE_QUIET_S = 1.0  # How long output must be quiet to be "stable"
AGENT_START_POST_STABILIZE_DELAY_S = 0.5  # Safety buffer after stabilization

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

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: Optional[TextIO] = None  # Will hold the locked file handle

        # Note: terminal_bridge and db are functional modules (no instantiation)
        # UI output management is now handled by UiAdapter (base class for Telegram, Slack, etc.)
        self.output_poller = OutputPoller()

        # Initialize unified adapter client (observer pattern - NO daemon reference)
        self.client = AdapterClient()

        # Initialize Codex watcher for file-based hooks
        self.codex_watcher = CodexWatcher(self.client, db_handle=db)

        # Initialize AgentCoordinator for agent events and cross-computer orchestration
        self.agent_coordinator = AgentCoordinator(self.client)
        self.client.on(cast(EventType, TeleClaudeEvents.AGENT_EVENT), self._handle_agent_event)

        # Debounce stop events (Gemini fires AfterAgent multiple times per turn)
        self._last_stop_time: dict[str, float] = {}
        self._stop_debounce_seconds = 5.0

        # Auto-discover and register event handlers
        for attr_name in dir(TeleClaudeEvents):
            if attr_name.startswith("_"):
                continue

            event_value = getattr(TeleClaudeEvents, attr_name)  # type: ignore[misc]
            if not isinstance(event_value, str):  # type: ignore[misc]
                continue

            # Commands use generic handler
            if event_value in COMMAND_EVENTS:
                self.client.on(cast(EventType, event_value), self._handle_command_event)  # type: ignore[arg-type]
                logger.debug("Auto-registered command: %s → _handle_command_event", event_value)
            else:
                # Non-commands (message, voice, topic_closed) use specific handlers
                handler_name = f"_handle_{event_value}"
                handler = getattr(self, handler_name, None)  # type: ignore[misc]

                if handler and callable(handler):  # type: ignore[misc]
                    self.client.on(cast(EventType, event_value), handler)  # type: ignore[misc]
                    logger.debug("Auto-registered handler: %s → %s", event_value, handler_name)
                else:
                    logger.debug("No handler for event: %s (skipped)", event_value)

        # Note: Adapters are loaded in client.start(), not here

        # Initialize MCP server (if enabled)
        self.mcp_server: Optional[TeleClaudeMCPServer] = None
        try:
            self.mcp_server = TeleClaudeMCPServer(
                adapter_client=self.client,
                terminal_bridge=terminal_bridge,
            )
            logger.info("MCP server object created successfully")
        except Exception as e:
            logger.error("Failed to create MCP server: %s", e, exc_info=True)

        # Shutdown event for graceful termination
        self.shutdown_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task[object]] = set()
        self.mcp_task: asyncio.Task[object] | None = None
        self.api_server_task: asyncio.Task[object] | None = None
        self._mcp_restart_lock = asyncio.Lock()
        self._mcp_restart_attempts = 0
        self._mcp_restart_window_start = 0.0
        self._last_mcp_probe_at = 0.0
        self._last_mcp_probe_ok: bool | None = None
        self._last_mcp_restart_at = 0.0
        self.hook_outbox_task: asyncio.Task[object] | None = None
        self.terminal_outbox_task: asyncio.Task[object] | None = None

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

    def _handle_mcp_task_done(self, task: asyncio.Task[object]) -> None:
        """Restart MCP server if task exits unexpectedly."""
        if self.shutdown_event.is_set():
            return
        try:
            task.result()
            logger.error("MCP server task exited unexpectedly; restarting")
        except asyncio.CancelledError:
            return
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("MCP server task crashed: %s; restarting", e, exc_info=True)
        self._schedule_mcp_restart("mcp_task_done")

    def _schedule_mcp_restart(self, reason: str) -> None:
        """Schedule an MCP server restart from sync contexts."""
        if self.shutdown_event.is_set():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("No running event loop to restart MCP server (%s)", reason)
            self.shutdown_event.set()
            return
        loop.create_task(self._restart_mcp_server(reason))

    async def _restart_mcp_server(self, reason: str) -> bool:
        """Restart the MCP server task in-process with backoff limits."""
        if not self.mcp_server:
            logger.error("MCP server not initialized; shutting down daemon")
            self.shutdown_event.set()
            return False
        async with self._mcp_restart_lock:
            now = asyncio.get_running_loop().time()
            if (
                self._mcp_restart_window_start == 0.0
                or (now - self._mcp_restart_window_start) > MCP_WATCH_RESTART_WINDOW_S
            ):
                self._mcp_restart_window_start = now
                self._mcp_restart_attempts = 0

            self._mcp_restart_attempts += 1
            if self._mcp_restart_attempts > MCP_WATCH_RESTART_MAX:
                logger.error(
                    "MCP restart limit exceeded; shutting down daemon",
                    reason=reason,
                    attempts=self._mcp_restart_attempts,
                )
                self.shutdown_event.set()
                return False

            logger.warning(
                "Restarting MCP server",
                reason=reason,
                attempt=self._mcp_restart_attempts,
                window_s=MCP_WATCH_RESTART_WINDOW_S,
            )

            try:
                await asyncio.wait_for(self.mcp_server.stop(), timeout=MCP_WATCH_RESTART_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Timed out stopping MCP server listener", timeout_s=MCP_WATCH_RESTART_TIMEOUT_S)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("MCP server stop failed: %s", exc, exc_info=True)

            if self.mcp_task:
                self.mcp_task.cancel()
                try:
                    await asyncio.wait_for(self.mcp_task, timeout=MCP_WATCH_RESTART_TIMEOUT_S)
                except asyncio.TimeoutError:
                    logger.warning("Timed out cancelling MCP server task", timeout_s=MCP_WATCH_RESTART_TIMEOUT_S)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning("MCP server task error during cancel: %s", exc, exc_info=True)

            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            self.mcp_task.add_done_callback(self._log_background_task_exception("mcp_server"))
            self.mcp_task.add_done_callback(self._handle_mcp_task_done)
            self._last_mcp_restart_at = asyncio.get_running_loop().time()
            logger.warning("MCP server restarted")
            return True

    async def _probe_mcp_socket(self, socket_path: str) -> bool:
        try:
            connect_awaitable = cast(
                Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
                asyncio.open_unix_connection(socket_path),
            )  # pyright: ignore[reportUnnecessaryCast]
            _reader, writer = await asyncio.wait_for(
                connect_awaitable,
                timeout=MCP_SOCKET_HEALTH_TIMEOUT_S,
            )  # type: ignore[misc]
        except (FileNotFoundError, ConnectionRefusedError, asyncio.TimeoutError, OSError) as exc:
            logger.warning("MCP socket health check failed: %s", exc)
            return False
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return True

    async def _check_mcp_socket_health(self) -> bool:
        now = asyncio.get_running_loop().time()
        if self._mcp_restart_lock.locked():
            return True
        if (now - self._last_mcp_restart_at) < MCP_SOCKET_HEALTH_STARTUP_GRACE_S:
            return True

        socket_path = Path(os.path.expandvars(MCP_SOCKET_PATH))
        snapshot = None
        if self.mcp_server and hasattr(self.mcp_server, "health_snapshot"):
            try:
                snapshot = await self.mcp_server.health_snapshot(socket_path)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning("MCP health snapshot failed: %s", exc, exc_info=True)

        if snapshot:
            is_serving = bool(snapshot.get("is_serving"))
            socket_exists = bool(snapshot.get("socket_exists"))
            active_connections = int(snapshot.get("active_connections") or 0)
            last_accept_age = snapshot.get("last_accept_age_s")

            if not is_serving or not socket_exists:
                logger.warning(
                    "MCP socket precheck failed",
                    is_serving=is_serving,
                    socket_exists=socket_exists,
                    active_connections=active_connections,
                    last_accept_age_s=last_accept_age,
                )
                return False

            if last_accept_age is not None and last_accept_age <= MCP_SOCKET_HEALTH_ACCEPT_GRACE_S:
                logger.debug(
                    "MCP socket healthy (recent accept)",
                    last_accept_age_s=last_accept_age,
                )
                return True
            if active_connections > 0:
                if (now - self._last_mcp_probe_at) < MCP_SOCKET_HEALTH_PROBE_INTERVAL_S:
                    return self._last_mcp_probe_ok is not False
                logger.warning(
                    "MCP socket accept stale; probing",
                    active_connections=active_connections,
                    last_accept_age_s=last_accept_age,
                )
                self._last_mcp_probe_at = now
                probe_ok = await self._probe_mcp_socket(str(socket_path))
                self._last_mcp_probe_ok = probe_ok
                return probe_ok
            if (now - self._last_mcp_probe_at) < MCP_SOCKET_HEALTH_PROBE_INTERVAL_S:
                return self._last_mcp_probe_ok is not False

        if (now - self._last_mcp_probe_at) < MCP_SOCKET_HEALTH_PROBE_INTERVAL_S:
            return self._last_mcp_probe_ok is not False

        self._last_mcp_probe_at = now
        probe_ok = await self._probe_mcp_socket(str(socket_path))
        self._last_mcp_probe_ok = probe_ok
        return probe_ok

    async def _mcp_watch_loop(self) -> None:
        failures = 0
        while not self.shutdown_event.is_set():
            await asyncio.sleep(MCP_WATCH_INTERVAL_S)

            if not self.mcp_task:
                logger.error("MCP server task missing; shutting down daemon")
                self.shutdown_event.set()
                return

            if self.mcp_task.done():
                await self._restart_mcp_server("mcp_task_done")
                failures = 0
                continue

            healthy = await self._check_mcp_socket_health()
            if healthy:
                if failures > 0:
                    logger.debug(
                        "MCP socket health recovered",
                        previous_failures=failures,
                    )
                failures = 0
                continue

            failures += 1
            logger.warning(
                "MCP socket health failure",
                failures=failures,
                threshold=MCP_WATCH_FAILURE_THRESHOLD,
            )
            if failures >= MCP_WATCH_FAILURE_THRESHOLD:
                ok = await self._restart_mcp_server("socket_unhealthy")
                failures = 0
                if not ok:
                    return

    def _hook_outbox_backoff(self, attempt: int) -> float:
        """Compute exponential backoff for hook outbox retries."""
        safe_attempt = max(1, attempt)
        delay: float = float(HOOK_OUTBOX_BASE_BACKOFF_S) * (2.0 ** (safe_attempt - 1))
        return min(delay, float(HOOK_OUTBOX_MAX_BACKOFF_S))

    def _is_retryable_hook_error(self, exc: Exception) -> bool:
        """Return True if hook dispatch errors should be retried."""
        if isinstance(exc, ValueError) and "not found" in str(exc):
            return False
        return True

    def _terminal_outbox_backoff(self, attempt: int) -> float:
        """Compute exponential backoff for terminal outbox retries."""
        safe_attempt = max(1, attempt)
        delay: float = float(TERMINAL_OUTBOX_BASE_BACKOFF_S) * (2.0 ** (safe_attempt - 1))
        return min(delay, float(TERMINAL_OUTBOX_MAX_BACKOFF_S))

    def _is_retryable_terminal_error(self, exc: Exception) -> bool:
        """Return True if terminal dispatch errors should be retried."""
        if isinstance(exc, ValueError) and "not found" in str(exc):
            return False
        return True

    def _coerce_message_metadata(self, metadata: TerminalOutboxMetadata) -> MessageMetadata:
        """Build MessageMetadata from outbox metadata payload."""
        adapter_type = metadata.get("adapter_type")
        message_thread_id = metadata.get("message_thread_id")
        parse_mode = metadata.get("parse_mode")
        raw_format = metadata.get("raw_format", False)
        channel_id = metadata.get("channel_id")
        title = metadata.get("title")
        project_dir = metadata.get("project_dir")
        channel_metadata = metadata.get("channel_metadata")
        auto_command = metadata.get("auto_command")

        return MessageMetadata(
            adapter_type=str(adapter_type) if adapter_type is not None else None,
            message_thread_id=int(message_thread_id) if isinstance(message_thread_id, int) else None,
            parse_mode=str(parse_mode) if parse_mode else "",
            raw_format=bool(raw_format),
            channel_id=str(channel_id) if channel_id is not None else None,
            title=str(title) if title is not None else None,
            project_dir=str(project_dir) if project_dir is not None else None,
            channel_metadata=cast(dict[str, object] | None, channel_metadata),  # noqa: loose-dict - MessageMetadata contract
            auto_command=str(auto_command) if auto_command is not None else None,
        )

    async def _dispatch_terminal_event(
        self,
        event_type: str,
        payload: TerminalOutboxPayload,
        metadata: MessageMetadata,
    ) -> TerminalOutboxResponse:
        """Dispatch a terminal-origin event directly via AdapterClient."""
        response = await self.client.handle_event(
            cast(EventType, event_type),
            cast(dict[str, object], payload),  # noqa: loose-dict - AdapterClient expects loose dict
            metadata,
        )
        if isinstance(response, dict):
            return cast(TerminalOutboxResponse, response)
        return cast(TerminalOutboxResponse, {"status": "success", "data": response})

    async def _dispatch_hook_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, object],  # noqa: loose-dict - Hook payload is dynamic JSON
    ) -> None:
        """Dispatch a hook event directly via AdapterClient."""
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"TeleClaude session {session_id} not found")

        transcript_path = data.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path:
            await db.update_session(session_id, native_log_file=transcript_path)

        teleclaude_pid = data.get("teleclaude_pid")
        teleclaude_tty = data.get("teleclaude_tty")
        if isinstance(teleclaude_pid, int) or isinstance(teleclaude_tty, str):
            updates: dict[str, object] = {}  # noqa: loose-dict - Hook payload is dynamic JSON
            if isinstance(teleclaude_pid, int):
                updates["native_pid"] = teleclaude_pid
            if isinstance(teleclaude_tty, str):
                if session.native_tty_path:
                    if session.native_tty_path != teleclaude_tty:
                        updates["tmux_tty_path"] = teleclaude_tty
                else:
                    updates["native_tty_path"] = teleclaude_tty
            if updates:
                await db.update_session(session_id, **updates)

        await self._ensure_output_polling(session)

        if event_type not in AgentHookEvents.ALL:
            logger.debug("Transcript capture event handled", event=event_type, session=session_id[:8])
            return

        event_type_name: EventType
        if event_type == AgentHookEvents.AGENT_ERROR:
            event_payload = cast(
                dict[str, object],  # noqa: loose-dict - Hook payload is dynamic JSON
                {
                    "session_id": session_id,
                    "message": str(data.get("message", "")),
                    "source": str(data.get("source")) if "source" in data else None,
                    "details": data.get("details") if isinstance(data.get("details"), dict) else None,
                },
            )
            event_type_name = TeleClaudeEvents.ERROR
        else:
            event_payload = cast(
                dict[str, object],  # noqa: loose-dict - Hook payload is dynamic JSON
                {"session_id": session_id, "event_type": event_type, "data": data},
            )
            event_type_name = TeleClaudeEvents.AGENT_EVENT

        response = await self.client.handle_event(
            event_type_name,
            event_payload,
            MessageMetadata(adapter_type="internal"),
        )
        if isinstance(response, dict):
            response_dict = cast(dict[str, object], response)  # noqa: loose-dict - Adapter response payload
            status = response_dict.get("status")
            if status == "error":
                raise ValueError(str(response_dict.get("error")))

    async def _hook_outbox_worker(self) -> None:
        """Drain hook outbox for durable, restart-safe delivery."""
        while not self.shutdown_event.is_set():
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            lock_cutoff = (now - timedelta(seconds=HOOK_OUTBOX_LOCK_TTL_S)).isoformat()
            rows = await db.fetch_hook_outbox_batch(now_iso, HOOK_OUTBOX_BATCH_SIZE, lock_cutoff)

            if not rows:
                await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
                continue

            for row in rows:
                if self.shutdown_event.is_set():
                    break
                claimed = await db.claim_hook_outbox(row["id"], now_iso, lock_cutoff)
                if not claimed:
                    continue

                try:
                    payload = cast(dict[str, object], json.loads(row["payload"]))  # noqa: loose-dict - Hook payload JSON
                except json.JSONDecodeError as exc:
                    logger.error("Hook outbox payload invalid", row_id=row["id"], error=str(exc))
                    await db.mark_hook_outbox_delivered(row["id"], error=str(exc))
                    continue

                try:
                    await self._dispatch_hook_event(row["session_id"], row["event_type"], payload)
                    await db.mark_hook_outbox_delivered(row["id"])
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    attempt = int(row.get("attempt_count", 0)) + 1
                    error_str = str(exc)
                    if not self._is_retryable_hook_error(exc):
                        logger.error(
                            "Hook outbox event dropped (non-retryable)",
                            row_id=row["id"],
                            attempt=attempt,
                            error=error_str,
                        )
                        await db.mark_hook_outbox_delivered(row["id"], error=error_str)
                        continue

                    delay = self._hook_outbox_backoff(attempt)
                    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    logger.error(
                        "Hook outbox dispatch failed (retrying)",
                        row_id=row["id"],
                        attempt=attempt,
                        next_attempt_in_s=round(delay, 2),
                        error=error_str,
                    )
                    await db.mark_hook_outbox_failed(row["id"], attempt, next_attempt, error_str)

    async def _terminal_outbox_worker(self) -> None:
        """Drain terminal outbox for telec-origin commands with responses."""
        while not self.shutdown_event.is_set():
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            lock_cutoff = (now - timedelta(seconds=TERMINAL_OUTBOX_LOCK_TTL_S)).isoformat()
            rows = await db.fetch_terminal_outbox_batch(now_iso, TERMINAL_OUTBOX_BATCH_SIZE, lock_cutoff)

            if not rows:
                await asyncio.sleep(TERMINAL_OUTBOX_POLL_INTERVAL_S)
                continue

            for row in rows:
                if self.shutdown_event.is_set():
                    break
                claimed = await db.claim_terminal_outbox(row["id"], now_iso, lock_cutoff)
                if not claimed:
                    continue

                try:
                    payload = cast(TerminalOutboxPayload, json.loads(row["payload"]))
                except json.JSONDecodeError as exc:
                    error_str = f"Invalid payload JSON: {exc}"
                    error_payload: dict[str, str] = {"status": "error", "error": ""}
                    error_payload["error"] = error_str
                    response_json = json.dumps(error_payload)
                    await db.mark_terminal_outbox_delivered(row["id"], response_json, error_str)
                    continue

                try:
                    metadata_raw = cast(TerminalOutboxMetadata, json.loads(row["metadata"]))
                    metadata = self._coerce_message_metadata(metadata_raw)
                    if not metadata.adapter_type:
                        metadata.adapter_type = "terminal"
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    error_str: str = f"Invalid metadata JSON: {exc}"
                    error_payload: dict[str, str] = {"status": "error", "error": error_str}  # type: ignore[misc]
                    response_json = json.dumps(error_payload)
                    await db.mark_terminal_outbox_delivered(row["id"], response_json, error_str)
                    continue

                try:
                    response = await self._dispatch_terminal_event(row["event_type"], payload, metadata)
                    response_json = json.dumps(response)
                    await db.mark_terminal_outbox_delivered(row["id"], response_json)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    attempt = int(row.get("attempt_count", 0)) + 1
                    error_str: str = str(exc)
                    if not self._is_retryable_terminal_error(exc):
                        error_payload: dict[str, str] = {"status": "error", "error": error_str}  # type: ignore[misc]
                        response_json = json.dumps(error_payload)
                        await db.mark_terminal_outbox_delivered(row["id"], response_json, error_str)
                        continue

                    delay = self._terminal_outbox_backoff(attempt)
                    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    logger.error(
                        "Terminal outbox dispatch failed (retrying)",
                        row_id=row["id"],
                        attempt=attempt,
                        next_attempt_in_s=round(delay, 2),
                        error=error_str,
                    )
                    await db.mark_terminal_outbox_failed(row["id"], attempt, next_attempt, error_str)

    def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None:
        """Create and track a background task."""
        task = asyncio.create_task(coro)
        self._track_background_task(task, label)

    async def _handle_command_event(self, event: str, context: CommandEventContext) -> object:
        """Generic handler for all command events.

        All commands route to handle_command() with args from context.

        Args:
            event: Command event type (new_session, cd, kill, etc.)
            context: Typed command event context

        Returns:
            Result from command handler
        """
        # Extract args from typed context
        args = context.args

        # Extract metadata fields from context
        metadata = MessageMetadata(
            adapter_type=context.adapter_type,
            message_thread_id=context.message_thread_id,
            title=context.title,
            project_dir=context.project_dir,
            channel_metadata=context.channel_metadata,
            auto_command=context.auto_command,
        )

        return await self.handle_command(event, args, context, metadata)

    async def _handle_message(self, _event: str, context: MessageEventContext) -> None:
        """Handler for MESSAGE events - pure business logic (cleanup already done).

        Args:
            _event: Event type (always "message") - unused but required by event handler signature
            context: Message event context (Pydantic)
        """
        # Pass typed context directly
        await self.handle_message(context.session_id, context.text, context)

    async def _handle_voice(self, _event: str, context: VoiceEventContext) -> None:
        """Handler for VOICE events - pure business logic (cleanup already done).

        Args:
            _event: Event type (always "voice") - unused but required by event handler signature
            context: Voice event context (Pydantic)
        """
        # Handle voice message using utility function
        transcribed = await voice_message_handler.handle_voice(
            session_id=context.session_id,
            audio_path=context.file_path,
            context=context,
            send_message=self._send_message_callback,
        )
        if not transcribed:
            return

        metadata = MessageMetadata(
            adapter_type=context.adapter_type,
            message_thread_id=context.message_thread_id,
        )
        await self.client.handle_event(
            event=TeleClaudeEvents.MESSAGE,
            payload={
                "session_id": context.session_id,
                "text": transcribed,
                "message_id": context.message_id,
            },
            metadata=metadata,
        )

    async def _handle_session_terminated(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_terminated events - user removed topic.

        Args:
            _event: Event type (always "session_terminated") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context

        session = await db.get_session(ctx.session_id)
        if not session:
            logger.warning("Session %s not found for termination event", ctx.session_id[:8])
            return

        logger.info("Handling session_terminated for %s", ctx.session_id[:8])
        await session_cleanup.terminate_session(
            ctx.session_id,
            self.client,
            reason="topic_closed",
            session=session,
        )

    async def _handle_file(self, _event: str, context: FileEventContext) -> None:
        """Handler for FILE events - pure business logic.

        Args:
            _event: Event type (always "file") - unused but required by event handler signature
            context: File event context (Pydantic)
        """
        await handle_file(
            session_id=context.session_id,
            file_path=context.file_path,
            filename=context.filename,
            context=context,
            send_message=self._send_message_callback,
        )

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

    async def _handle_agent_event(self, _event: str, context: EventContext) -> None:
        """Central handler for AGENT_EVENT (formerly CLAUDE_EVENT).

        Orchestrates summarization, title updates, and coordination.
        """
        # We know this is AgentEventContext because of the event type registration
        if not isinstance(context, AgentEventContext):
            return

        agent_event_type = context.event_type

        # Handle STOP event in background to prevent hook timeout during summarization
        if agent_event_type == AgentHookEvents.AGENT_STOP:
            task = asyncio.create_task(self._process_agent_stop(context))
            task.add_done_callback(self._log_background_task_exception("process_agent_stop"))
            return

        # Dispatch other events synchronously
        if agent_event_type == AgentHookEvents.AGENT_SESSION_START:
            await self.agent_coordinator.handle_session_start(context)
        elif agent_event_type == AgentHookEvents.AGENT_NOTIFICATION:
            await self.agent_coordinator.handle_notification(context)
        elif agent_event_type == AgentHookEvents.AGENT_SESSION_END:
            await self.agent_coordinator.handle_session_end(context)

    async def _process_agent_stop(self, context: AgentEventContext) -> None:
        """Process agent stop event (summarization + coordination)."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        # Debounce: skip if we processed a stop event for this session recently
        # Gemini's AfterAgent fires multiple times per turn (after each agent step)
        now = time.monotonic()
        last_stop = self._last_stop_time.get(session_id, 0.0)
        if now - last_stop < self._stop_debounce_seconds:
            logger.debug("Debouncing stop event for session %s (%.1fs since last)", session_id[:8], now - last_stop)
            return
        self._last_stop_time[session_id] = now

        if source_computer:
            await self.agent_coordinator.handle_stop(context)
            return

        try:
            session = await db.get_session(session_id)
            if not session or not session.active_agent:
                raise ValueError(f"Session {session_id[:8]} missing active_agent metadata")

            native_session_id = str(payload.session_id) if payload.session_id else ""
            if native_session_id:
                await db.update_session(session_id, native_session_id=native_session_id)

            transcript_path = payload.transcript_path or session.native_log_file
            if not transcript_path:
                raise ValueError(f"Session {session_id[:8]} missing transcript path on stop event")
            payload.transcript_path = transcript_path

            agent_name = AgentName.from_str(session.active_agent)

            # Try AI summarization, fall back to raw transcript on API failure
            try:
                title, summary = await summarize(agent_name, transcript_path)
            except Exception as sum_err:
                logger.warning(
                    "Summarization failed for %s, falling back to raw transcript: %s", session_id[:8], sum_err
                )
                title = None
                summary = parse_session_transcript(
                    transcript_path, title="", agent_name=agent_name, tail_chars=UI_MESSAGE_MAX_CHARS
                )

            payload.summary = summary
            payload.title = title
            payload.raw["summary"] = payload.summary
            payload.raw["title"] = payload.title

            if payload.title:
                await self._update_session_title(session_id, payload.title)

            session = await db.get_session(session_id)
            if not session:
                raise ValueError(f"Summary feedback requires active session: {session_id}")
            # Use feedback=True to clean up old feedback (transcription, etc.) before sending summary
            await self.client.send_message(
                session, summary, metadata=MessageMetadata(adapter_type="internal"), feedback=True
            )

            # Track summary as last output (only source of truth for last_output)
            if summary:
                await db.update_session(session_id, last_feedback_received=summary[:200])

            # Dispatch to coordinator
            await self.agent_coordinator.handle_stop(context)

        except Exception as e:
            logger.error("Failed to process agent stop event for session %s: %s", session_id[:8], e)
            # Try to report error to user
            try:
                session = await db.get_session(session_id)
                if session:
                    await self.client.send_message(
                        session,
                        f"Error processing session summary: {e}",
                        metadata=MessageMetadata(adapter_type="internal"),
                    )
            except Exception:
                pass

    async def _execute_auto_command(self, session_id: str, auto_command: str) -> dict[str, str]:
        """Execute a post-session auto_command and return status/message."""
        auto_context = CommandEventContext(session_id=session_id, args=[])
        cmd_name, auto_args = parse_command_string(auto_command)

        if cmd_name == "agent_then_message":
            return await self._handle_agent_then_message(session_id, auto_args)

        if cmd_name == TeleClaudeEvents.AGENT_START and auto_args:
            agent_name = auto_args.pop(0)
            await command_handlers.handle_agent_start(
                auto_context, agent_name, auto_args, self.client, self._execute_terminal_command
            )
            return {"status": "success"}

        if cmd_name == TeleClaudeEvents.AGENT_RESUME and auto_args:
            agent_name = auto_args.pop(0)
            await command_handlers.handle_agent_resume(
                auto_context, agent_name, auto_args, self.client, self._execute_terminal_command
            )
            return {"status": "success"}

        logger.warning("Unknown or malformed auto_command: %s", auto_command)
        return {"status": "error", "message": f"Unknown or malformed auto_command: {auto_command}"}

    async def _handle_agent_then_message(self, session_id: str, args: list[str]) -> dict[str, str]:
        """Start agent, wait for TUI to stabilize, then inject message."""
        if len(args) < 3:
            return {"status": "error", "message": "agent_then_message requires agent, thinking_mode, message"}

        agent_name = args[0]
        thinking_mode = args[1]
        message = " ".join(args[2:]).strip()
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        logger.debug("agent_then_message: agent=%s mode=%s msg=%s", agent_name, thinking_mode, message[:50])
        auto_context = CommandEventContext(session_id=session_id, args=[])
        thinking_args: list[str] = [thinking_mode]
        await command_handlers.handle_agent_start(
            auto_context,
            agent_name,
            thinking_args,
            self.client,
            self._execute_terminal_command,
        )

        session = await db.get_session(session_id)
        if not session:
            return {"status": "error", "message": "Session not found after creation"}

        # Step 1: Wait for agent process to start
        deadline = time.monotonic() + AGENT_START_TIMEOUT_S
        while time.monotonic() < deadline:
            is_running = await terminal_io.is_process_running(session)
            if is_running:
                break
            await asyncio.sleep(AGENT_START_POLL_INTERVAL_S)
        else:
            logger.warning("agent_then_message timed out waiting for agent start (session=%s)", session_id[:8])
            return {"status": "error", "message": "Timeout waiting for agent to start"}

        # Step 2: Initial settle delay
        await asyncio.sleep(AGENT_START_SETTLE_DELAY_S)

        # Step 3: Wait for output to stabilize (TUI banner + MCP loading complete)
        logger.debug("agent_then_message: waiting for TUI to stabilize (session=%s)", session_id[:8])
        stabilized, _stable_tail = await self._wait_for_output_stable(
            session,
            AGENT_START_STABILIZE_TIMEOUT_S,
            AGENT_START_STABILIZE_QUIET_S,
        )
        if not stabilized:
            logger.warning(
                "agent_then_message: stabilization timed out after %.1fs, proceeding anyway (session=%s)",
                AGENT_START_STABILIZE_TIMEOUT_S,
                session_id[:8],
            )

        # Step 4: Post-stabilization safety buffer
        await asyncio.sleep(AGENT_START_POST_STABILIZE_DELAY_S)

        # Step 5: Now inject the message (TUI should be ready)
        logger.debug("agent_then_message: injecting message to session=%s", session_id[:8])

        active_agent = session.active_agent

        sanitized_message = terminal_io.wrap_bracketed_paste(message)
        pasted = await terminal_io.send_text(
            session,
            sanitized_message,
            working_dir=session.working_directory,
            send_enter=False,
            active_agent=active_agent,
        )
        if not pasted:
            return {"status": "error", "message": "Failed to paste command into tmux"}

        # Step 6: Small delay before sending Enter
        await asyncio.sleep(AGENT_START_POST_INJECT_DELAY_S)
        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)

        # Step 7: Send Enter and wait for command acceptance
        accepted = await self._confirm_command_acceptance(session)
        if not accepted:
            logger.warning(
                "agent_then_message timed out waiting for command acceptance (session=%s)",
                session_id[:8],
            )
            return {"status": "error", "message": "Timeout waiting for command acceptance"}

        return {"status": "success", "message": "Message injected after agent start"}

    async def _pane_output_snapshot(self, session: Session) -> tuple[str, str]:
        output = await terminal_bridge.capture_pane(session.tmux_session_name)
        if not output:
            return "", ""
        tail = output[-AGENT_START_OUTPUT_TAIL_CHARS:]
        digest = hashlib.sha256(tail.encode("utf-8", errors="replace")).hexdigest()
        return tail, digest

    async def _wait_for_output_stable(
        self,
        session: Session,
        timeout_s: float,
        quiet_s: float,
    ) -> tuple[bool, str]:
        """Wait for output to stop changing (stabilize).

        Polls tmux output and waits until it hasn't changed for `quiet_s` seconds.
        This detects when TUI banner + MCP loading is complete.

        Args:
            session: The session to monitor
            timeout_s: Maximum time to wait for stabilization
            quiet_s: How long output must be unchanged to be considered stable

        Returns:
            Tuple of (stabilized, last_output_tail)
        """
        deadline = time.monotonic() + timeout_s
        last_tail, last_digest = await self._pane_output_snapshot(session)
        quiet_since = time.monotonic()

        while time.monotonic() < deadline:
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
            current_tail, current_digest = await self._pane_output_snapshot(session)

            if current_digest != last_digest:
                # Output changed - reset quiet timer
                last_tail, last_digest = current_tail, current_digest
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= quiet_s:
                # Output has been stable for quiet_s seconds
                logger.debug("Output stabilized after %.1fs quiet", quiet_s)
                return True, current_tail

        logger.debug("Output stabilization timed out after %.1fs", timeout_s)
        return False, last_tail

    @staticmethod
    def _summarize_output_change(before: str, after: str) -> OutputChangeSummary:
        if before == after:
            return {"changed": False, "reason": "identical"}

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

        return {
            "changed": True,
            "before_len": len(before),
            "after_len": len(after),
            "diff_index": diff_index,
            "before_snippet": repr(before_snippet),
            "after_snippet": repr(after_snippet),
        }

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
            await terminal_io.send_enter(session)
            await asyncio.sleep(AGENT_START_ENTER_INTER_DELAY_S)
            await terminal_io.send_enter(session)

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

    async def _handle_error(self, _event: str, context: EventContext) -> None:
        """Handle error events (fail-fast contract violations, hook issues)."""
        if not isinstance(context, ErrorEventContext):
            return

        session = await db.get_session(context.session_id)
        if not session:
            logger.error("Error event for unknown session %s: %s", context.session_id[:8], context.message)
            return

        source = f" ({context.source})" if context.source else ""
        message = f"Error{source}: {context.message}"
        await self.client.send_message(session, message, metadata=MessageMetadata(adapter_type="internal"))

    async def _update_session_title(self, session_id: str, title: str) -> None:
        """Update session title in DB and UI.

        Only updates once - when description is still "Untitled".
        Subsequent agent_stop events preserve the first LLM-generated title.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        # Parse the title to extract prefix and description
        prefix, description = parse_session_title(session.title)
        if not prefix:
            return

        # Only update if description is still "Untitled" (or "Untitled (N)")
        if not description or not re.search(r"^Untitled( \(\d+\))?$", description):
            return  # Already has LLM-generated title - skip

        new_title = f"{prefix}{title}"
        await db.update_session(session_id, title=new_title)
        # db.update_session emits SESSION_UPDATED, which adapters listen to.
        # So UI updates automatically!
        logger.info("Updated title: %s", new_title)

    async def _handle_deploy(self, _args: DeployArgs) -> None:  # pylint: disable=too-many-locals  # Deployment requires multiple state variables
        """Execute deployment: git pull + restart daemon via service manager.

        Args:
            _args: Deploy arguments (verify_health currently unused)
        """
        # Get Redis adapter for status updates
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            logger.error("Redis adapter not available, cannot update deploy status")
            return

        redis_adapter: RedisAdapter = redis_adapter_base
        status_key = f"system_status:{config.computer.name}:deploy"
        redis_client = redis_adapter._require_redis()

        async def update_status(payload: DeployStatusPayload | DeployErrorPayload) -> None:
            await redis_client.set(status_key, json.dumps(payload))

        try:
            # 1. Write deploying status
            deploying_payload: DeployStatusPayload = {"status": "deploying", "timestamp": time.time()}
            await update_status(deploying_payload)
            logger.info("Deploy: marked status as deploying")

            # 2. Git pull with automatic merge commit handling
            logger.info("Deploy: executing git pull...")

            # Configure git to auto-commit merges (non-interactive)
            await asyncio.create_subprocess_exec(
                "git",
                "config",
                "pull.rebase",
                "false",
                cwd=Path(__file__).parent.parent,
            )

            # Pull with merge strategy (accepts default merge commit message)
            result = await asyncio.create_subprocess_exec(
                "git",
                "pull",
                "--no-edit",  # Use default merge commit message
                cwd=Path(__file__).parent.parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                # Capture both stdout and stderr (git sends different errors to different streams)
                # Uncommitted changes → stderr, merge conflicts → stdout
                stdout_msg = stdout.decode("utf-8").strip()
                stderr_msg = stderr.decode("utf-8").strip()
                error_msg = f"{stderr_msg}\n{stdout_msg}".strip()
                logger.error("Deploy: git pull failed: %s", error_msg)
                git_error_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": f"git pull failed: {error_msg}",
                }
                await update_status(git_error_payload)
                return

            output = stdout.decode("utf-8")
            logger.info("Deploy: git pull successful - %s", output.strip())

            # 3. Run make install (update dependencies)
            logger.info("Deploy: running make install...")
            install_result = await asyncio.create_subprocess_exec(
                "make",
                "install",
                cwd=Path(__file__).parent.parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for install to complete with 60s timeout
            try:
                install_stdout, install_stderr = await asyncio.wait_for(install_result.communicate(), timeout=60.0)  # type: ignore[misc]
            except asyncio.TimeoutError:
                logger.error("Deploy: make install timed out after 60s")
                timeout_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": "make install timed out after 60s",
                }
                await update_status(timeout_payload)
                return

            if install_result.returncode != 0:
                error_msg = install_stderr.decode("utf-8")
                logger.error("Deploy: make install failed: %s", error_msg)
                install_error_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": f"make install failed: {error_msg}",
                }
                await update_status(install_error_payload)
                return

            install_output = install_stdout.decode("utf-8")
            logger.info("Deploy: make install successful - %s", install_output.strip())

            # 4. Write restarting status
            restarting_payload: DeployStatusPayload = {"status": "restarting", "timestamp": time.time()}
            await update_status(restarting_payload)

            # 5. Exit to trigger service manager restart
            # With Restart=on-failure, any non-zero exit triggers restart
            # Use exit code 42 to indicate intentional deploy restart (not a crash)
            logger.info("Deploy: exiting with code 42 to trigger service manager restart")
            os._exit(42)

        except Exception as e:
            logger.error("Deploy failed: %s", e, exc_info=True)
            exception_payload: DeployErrorPayload = {"status": "error", "error": str(e)}
            await update_status(exception_payload)

    async def _handle_health_check(self) -> None:
        """Handle health check requested."""
        logger.info("Health check requested")

    def _get_output_file_path(self, session_id: str) -> Path:
        """Get output file path for a session (delegates to session_utils)."""
        return get_output_file(session_id)

    async def _send_message_callback(
        self,
        sid: str,
        msg: str,
        metadata: MessageMetadata | None = None,
    ) -> Optional[str]:
        """Callback for handlers that need to send feedback messages.

        Uses send_feedback to delete old feedback before sending new.
        Wraps AdapterClient.send_feedback to match handler signature.

        Args:
            sid: Session ID
            msg: Message text
            metadata: Optional message metadata

        Returns:
            message_id if sent, None otherwise
        """
        session = await db.get_session(sid)
        if not session:
            logger.warning("Session %s not found for message", sid[:8])
            return None
        return await self.client.send_message(session, msg, metadata=metadata, feedback=True)

    def _acquire_lock(self) -> None:
        """Acquire daemon lock using PID file with fcntl advisory locking.

        Production-grade approach: atomic, reliable, OS-standard.
        No unreliable ps aux grepping needed.

        Raises:
            DaemonLockError: If another daemon instance is already running
        """

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

    def _get_adapter_by_type(self, adapter_type: str) -> BaseAdapter:
        """Get adapter by type.

        Args:
            adapter_type: Adapter type name

        Returns:
            BaseAdapter instance

        Raises:
            ValueError: If adapter type not loaded
        """
        adapter = self.client.adapters.get(adapter_type)
        if not adapter:
            raise ValueError(
                f"No adapter available for type '{adapter_type}'. Available: {list(self.client.adapters.keys())}"
            )
        return adapter

    async def _execute_terminal_command(
        self,
        session_id: str,
        command: str,
        _message_id: Optional[str] = None,
        start_polling: bool = True,
    ) -> bool:
        """Execute command in terminal and start polling if needed.

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

        sanitized_command = terminal_io.wrap_bracketed_paste(command)
        success = await terminal_io.send_text(
            session,
            sanitized_command,
            working_dir=session.working_directory,
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
        # Handlers know whether their commands need polling (cd=instant, claude=long-running)
        if start_polling:
            await self._start_polling_for_session(session_id, session.tmux_session_name)

        logger.info("Executed command in session %s: %s (polling=%s)", session_id[:8], command, start_polling)
        return True

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting TeleClaude daemon...")

        # Initialize database
        await db.initialize()
        logger.info("Database initialized")

        # Wire DB to AdapterClient for UI updates
        db.set_client(self.client)

        # Start all adapters via AdapterClient (network operation - can fail)
        await self.client.start()

        # Initialize voice handler (side effect - only after network succeeds)
        init_voice_handler()
        logger.info("Voice handler initialized")

        # Check if we just restarted from deployment
        redis_adapter_base = self.client.adapters.get("redis")
        if redis_adapter_base and isinstance(redis_adapter_base, RedisAdapter):
            redis_adapter: RedisAdapter = redis_adapter_base
            if redis_adapter.redis:
                status_key = f"system_status:{config.computer.name}:deploy"
                status_data = await redis_adapter.redis.get(status_key)
                if status_data:
                    try:
                        status_raw: object = json.loads(status_data.decode("utf-8"))  # type: ignore[misc]
                        if isinstance(status_raw, dict) and status_raw.get("status") == "restarting":  # type: ignore[misc]
                            # We successfully restarted from deployment
                            await redis_adapter.redis.set(
                                status_key,
                                json.dumps({"status": "deployed", "timestamp": time.time(), "pid": os.getpid()}),  # type: ignore[misc]
                            )
                            logger.info("Deployment complete, daemon restarted successfully (PID: %s)", os.getpid())
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning("Failed to parse deploy status: %s", e)

        # Start MCP server in background task (if enabled)
        logger.debug("MCP server object exists: %s", self.mcp_server is not None)
        if self.mcp_server:
            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            self.mcp_task.add_done_callback(self._log_background_task_exception("mcp_server"))
            self.mcp_task.add_done_callback(self._handle_mcp_task_done)
            # Avoid health checks during initial MCP startup.
            self._last_mcp_restart_at = asyncio.get_running_loop().time()
            logger.info("MCP server starting in background")

            self.mcp_watch_task = asyncio.create_task(self._mcp_watch_loop())
            self.mcp_watch_task.add_done_callback(self._log_background_task_exception("mcp_watch"))
            logger.info("MCP server watch task started")
        else:
            logger.warning("MCP server not started - object is None")

        # Start periodic cleanup task (runs every hour)
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self.cleanup_task.add_done_callback(self._log_background_task_exception("periodic_cleanup"))
        logger.info("Periodic cleanup task started (72h session lifecycle)")

        # Start polling watcher (keeps pollers aligned with tmux foreground state)
        self.poller_watch_task = asyncio.create_task(self._poller_watch_loop())
        self.poller_watch_task.add_done_callback(self._log_background_task_exception("poller_watch"))
        logger.info("Poller watch task started")

        self.hook_outbox_task = asyncio.create_task(self._hook_outbox_worker())
        self.hook_outbox_task.add_done_callback(self._log_background_task_exception("hook_outbox"))
        logger.info("Hook outbox worker started")

        self.terminal_outbox_task = asyncio.create_task(self._terminal_outbox_worker())
        self.terminal_outbox_task.add_done_callback(self._log_background_task_exception("terminal_outbox"))
        logger.info("Terminal outbox worker started")

        # CodexWatcher disabled - using native Codex notify hook instead (2026-01)
        # Keeping code for fallback. Remove after notify hook proven stable.
        # await self.codex_watcher.start()
        # logger.info("Session watcher started")

        # Start REST API server in background task
        self.api_server_task = asyncio.create_task(self._run_api_server())
        self.api_server_task.add_done_callback(self._log_background_task_exception("api_server"))
        logger.info("REST API server starting in background")

        logger.info("TeleClaude is running. Press Ctrl+C to stop.")

    async def _run_api_server(self) -> None:
        """Run the REST API server on Unix socket."""
        try:
            # Import here to avoid circular imports
            import uvicorn

            from teleclaude.api import app
            from teleclaude.api.routes import set_mcp_server

            # Wire MCP server instance to routes
            if self.mcp_server:
                set_mcp_server(self.mcp_server)
            else:
                logger.warning("MCP server not available for API routes")

            config_obj = uvicorn.Config(
                app,
                uds="/tmp/teleclaude-api.sock",
                log_level="warning",
            )
            server = uvicorn.Server(config_obj)
            logger.info("REST API server listening on /tmp/teleclaude-api.sock")
            await server.serve()
        except Exception as e:
            logger.error("REST API server crashed: %s", e, exc_info=True)
            raise

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping TeleClaude daemon...")

        # Stop MCP server task
        if self.mcp_task:
            self.mcp_task.cancel()
            try:
                await self.mcp_task
            except asyncio.CancelledError:
                pass
            logger.info("MCP server stopped")

        if hasattr(self, "mcp_watch_task"):
            self.mcp_watch_task.cancel()
            try:
                await self.mcp_watch_task
            except asyncio.CancelledError:
                pass
            logger.info("MCP server watch task stopped")

        # Stop REST API server task
        if self.api_server_task:
            self.api_server_task.cancel()
            try:
                await self.api_server_task
            except asyncio.CancelledError:
                pass
            logger.info("REST API server stopped")

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

        if self.terminal_outbox_task:
            self.terminal_outbox_task.cancel()
            try:
                await self.terminal_outbox_task
            except asyncio.CancelledError:
                pass
            logger.info("Terminal outbox worker stopped")

        # Stop session watcher
        if hasattr(self, "codex_watcher"):
            await self.codex_watcher.stop()
            logger.info("Session watcher stopped")

        # Stop all adapters
        for adapter_name, adapter in self.client.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            await adapter.stop()

        # Close database
        await db.close()

        logger.info("Daemon stopped")

    async def handle_command(
        self, command: str, args: list[str], context: EventContext, metadata: MessageMetadata
    ) -> object:  # Handler return types vary  # pylint: disable=too-many-branches
        """Handle bot commands.

        Args:
            command: Event name from TeleClaudeEvents (e.g., "new_session", "list_projects")
            args: Command arguments
            context: Command context (session_id, args)
            metadata: Message metadata (adapter_type, message_thread_id, etc.)

        Note: Handlers decorated with @with_session have modified signatures (decorator injects session parameter).
        """
        logger.debug("Command received: %s %s", command, args)

        if command == TeleClaudeEvents.NEW_SESSION:
            result = await command_handlers.handle_create_session(context, args, metadata, self.client)
            logger.debug(
                "NEW_SESSION result: session_id=%s, auto_command=%s",
                result.get("session_id"),
                metadata.auto_command,
            )

            # Handle auto_command if specified (e.g., start Claude after session creation)
            if metadata.auto_command and result.get("session_id"):
                session_id = str(result["session_id"])
                auto_command = metadata.auto_command

                if metadata.adapter_type in ("redis", "mcp"):
                    self._queue_background_task(
                        self._execute_auto_command(session_id, auto_command),
                        f"auto_command:{session_id[:8]}",
                    )
                    result["auto_command_status"] = "queued"
                    result["auto_command_message"] = "Auto-command queued"
                else:
                    auto_result = await self._execute_auto_command(session_id, auto_command)
                    result["auto_command_status"] = auto_result.get("status", "error")
                    if auto_result.get("message"):
                        result["auto_command_message"] = auto_result["message"]

            return result
        elif command == TeleClaudeEvents.LIST_SESSIONS:
            # LIST_SESSIONS is ephemeral command (MCP/Redis only) - return envelope directly
            return await command_handlers.handle_list_sessions()
        elif command == TeleClaudeEvents.LIST_PROJECTS:
            return await command_handlers.handle_list_projects()
        elif command == TeleClaudeEvents.GET_SESSION_DATA:
            # Parse args: [since_timestamp] [until_timestamp] [tail_chars]
            #
            # NOTE: When commands are sent over Redis as a space-separated string,
            # empty placeholders collapse (multiple spaces become one) so callers
            # cannot reliably send "" for since/until. Support flexible forms:
            # - /get_session_data
            # - /get_session_data 2000
            # - /get_session_data <since> 2000
            # - /get_session_data <since> <until> 2000
            since_timestamp: Optional[str] = None
            until_timestamp: Optional[str] = None
            tail_chars = 5000

            if len(args) == 1:
                # Either tail_chars or since_timestamp
                try:
                    tail_chars = int(args[0])
                except ValueError:
                    since_timestamp = args[0] or None
            elif len(args) == 2:
                # Either since+tail_chars or since+until
                try:
                    tail_chars = int(args[1])
                    since_timestamp = args[0] or None
                except ValueError:
                    since_timestamp = args[0] or None
                    until_timestamp = args[1] or None
            elif len(args) >= 3:
                since_timestamp = args[0] or None
                until_timestamp = args[1] or None
                try:
                    tail_chars = int(args[2]) if args[2] else 5000
                except ValueError:
                    tail_chars = 5000
            return await command_handlers.handle_get_session_data(context, since_timestamp, until_timestamp, tail_chars)
        elif command == TeleClaudeEvents.GET_COMPUTER_INFO:
            logger.info(">>> BRANCH MATCHED: GET_COMPUTER_INFO")
            result = await command_handlers.handle_get_computer_info()  # type: ignore[assignment]
            logger.info("handle_get_computer_info returned: %s", result)
            return result
        elif command == TeleClaudeEvents.CANCEL:
            return await command_handlers.handle_cancel_command(context, self.client, self._start_polling_for_session)
        elif command == TeleClaudeEvents.CANCEL_2X:
            return await command_handlers.handle_cancel_command(
                context, self.client, self._start_polling_for_session, double=True
            )
        elif command == TeleClaudeEvents.KILL:
            return await command_handlers.handle_kill_command(context, self.client, self._start_polling_for_session)
        elif command == TeleClaudeEvents.ESCAPE:
            return await command_handlers.handle_escape_command(
                context, args, self.client, self._start_polling_for_session
            )
        elif command == TeleClaudeEvents.ESCAPE_2X:
            return await command_handlers.handle_escape_command(
                context,
                args,
                self.client,
                self._start_polling_for_session,
                double=True,
            )
        elif command == TeleClaudeEvents.CTRL:
            return await command_handlers.handle_ctrl_command(
                context, args, self.client, self._start_polling_for_session
            )
        elif command == TeleClaudeEvents.TAB:
            return await command_handlers.handle_tab_command(context, self.client, self._start_polling_for_session)
        elif command == TeleClaudeEvents.SHIFT_TAB:
            return await command_handlers.handle_shift_tab_command(
                context, args, self.client, self._start_polling_for_session
            )
        elif command == TeleClaudeEvents.BACKSPACE:
            return await command_handlers.handle_backspace_command(
                context, args, self.client, self._start_polling_for_session
            )
        elif command == TeleClaudeEvents.ENTER:
            return await command_handlers.handle_enter_command(context, self.client, self._start_polling_for_session)
        elif command == TeleClaudeEvents.KEY_UP:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._start_polling_for_session, "up"
            )
        elif command == TeleClaudeEvents.KEY_DOWN:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._start_polling_for_session, "down"
            )
        elif command == TeleClaudeEvents.KEY_LEFT:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._start_polling_for_session, "left"
            )
        elif command == TeleClaudeEvents.KEY_RIGHT:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._start_polling_for_session, "right"
            )
        elif command == TeleClaudeEvents.RENAME:
            return await command_handlers.handle_rename_session(context, args, self.client)
        elif command == TeleClaudeEvents.CD:
            return await command_handlers.handle_cd_session(context, args, self.client, self._execute_terminal_command)
        elif command == TeleClaudeEvents.AGENT_START:
            agent_name = args.pop(0) if args else ""
            return await command_handlers.handle_agent_start(
                context, agent_name, args, self.client, self._execute_terminal_command
            )
        elif command == TeleClaudeEvents.AGENT_RESUME:
            agent_name = args.pop(0) if args else ""
            return await command_handlers.handle_agent_resume(
                context, agent_name, args, self.client, self._execute_terminal_command
            )
        elif command == TeleClaudeEvents.AGENT_RESTART:
            agent_name = args.pop(0) if args else ""
            return await command_handlers.handle_agent_restart(
                context, agent_name, args, self.client, self._execute_terminal_command
            )
        elif command == "exit":
            return await command_handlers.handle_exit_session(context, self.client)

        return None

    async def handle_message(self, session_id: str, text: str, _context: EventContext) -> None:
        """Handle incoming text messages (commands for terminal)."""
        logger.debug("Message for session %s: %s...", session_id[:8], text[:50])

        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Check for stale session (on-the-fly cleanup)
        was_stale = await session_cleanup.cleanup_stale_session(session_id, self.client)
        if was_stale:
            logger.warning("Session %s was stale and has been cleaned up", session_id[:8])
            return

        # Get active agent for agent-specific escaping
        active_agent = session.active_agent

        sanitized_text = terminal_io.wrap_bracketed_paste(text)

        # Send command to terminal (will create fresh session if needed)
        success = await terminal_io.send_text(
            session,
            sanitized_text,
            working_dir=session.working_directory,
            active_agent=active_agent,
        )

        if not success:
            logger.error("Failed to send command to session %s", session_id[:8])
            await self.client.send_message(session, "Failed to send command to terminal", metadata=MessageMetadata())
            return

        # Update activity
        await db.update_last_activity(session_id)

        # Start polling for output updates
        await self._start_polling_for_session(session_id, session.tmux_session_name)
        logger.debug("Started polling for session %s", session_id[:8])

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up inactive sessions (72h lifecycle) and orphaned tmux sessions."""
        first_run = True
        while True:
            try:
                if not first_run:
                    await asyncio.sleep(3600)  # Run every hour
                first_run = False

                # Clean up sessions inactive for 72+ hours
                await self._cleanup_inactive_sessions()

                # Clean up orphaned sessions (tmux gone but DB says active)
                await session_cleanup.cleanup_all_stale_sessions(self.client)

                # Clean up orphan tmux sessions (tmux exists but no DB entry)
                await session_cleanup.cleanup_orphan_tmux_sessions()

                # Clean up orphan workspace directories (workspace exists but no DB entry)
                await session_cleanup.cleanup_orphan_workspaces()

                # Clean up orphan MCP wrappers (ppid=1) to avoid FD leaks
                await session_cleanup.cleanup_orphan_mcp_wrappers()

                # Clean up stale voice assignments (7 day TTL)
                await db.cleanup_stale_voice_assignments()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic cleanup: %s", e)

    async def _poller_watch_loop(self) -> None:
        """Watch tmux foreground commands and ensure pollers are running when needed."""
        while True:
            try:
                await self._poller_watch_iteration()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in poller watch loop: %s", e)
            await asyncio.sleep(1.0)

    async def _poller_watch_iteration(self) -> None:
        """Run a single poller watch iteration (extracted for testing)."""
        sessions = await db.get_active_sessions()
        for session in sessions:
            if (
                not session.adapter_metadata
                or not session.adapter_metadata.telegram
                or not session.adapter_metadata.telegram.topic_id
            ):
                try:
                    await self.client.ensure_ui_channels(session, session.title)
                except Exception as exc:
                    logger.warning(
                        "Failed to ensure UI channels for session %s: %s",
                        session.session_id[:8],
                        exc,
                    )

            if not await terminal_bridge.session_exists(session.tmux_session_name, log_missing=False):
                await session_cleanup.cleanup_stale_session(session.session_id, self.client)
                continue
            if await terminal_bridge.is_pane_dead(session.tmux_session_name):
                await session_cleanup.terminate_session(
                    session.session_id,
                    self.client,
                    reason="pane_dead",
                    session=session,
                )
                continue
            if await polling_coordinator.is_polling(session.session_id):
                continue

            await polling_coordinator.schedule_polling(
                session_id=session.session_id,
                tmux_session_name=session.tmux_session_name,
                output_poller=self.output_poller,
                adapter_client=self.client,
                get_output_file=self._get_output_file_path,
            )

    async def _cleanup_inactive_sessions(self) -> None:
        """Clean up sessions inactive for 72+ hours."""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=72)
            sessions = await db.list_sessions()

            for session in sessions:
                # Check last_activity timestamp
                if not session.last_activity:
                    logger.warning("No last_activity for session %s", session.session_id[:8])
                    continue

                if session.last_activity < cutoff_time:
                    logger.info(
                        "Cleaning up inactive session %s (inactive for %s)",
                        session.session_id[:8],
                        datetime.now(timezone.utc) - session.last_activity,
                    )

                    await session_cleanup.terminate_session(
                        session.session_id,
                        self.client,
                        reason="inactive_72h",
                        session=session,
                    )
                    logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

        except Exception as e:
            logger.error("Error cleaning up inactive sessions: %s", e)

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
            get_output_file=self._get_output_file_path,
        )

    async def _ensure_output_polling(self, session: Session) -> None:
        if await polling_coordinator.is_polling(session.session_id):
            return
        if (
            not session.adapter_metadata
            or not session.adapter_metadata.telegram
            or not session.adapter_metadata.telegram.topic_id
        ):
            try:
                await self.client.ensure_ui_channels(session, session.title)
            except Exception as exc:
                logger.warning(
                    "Failed to create UI channel for session %s: %s",
                    session.session_id[:8],
                    exc,
                )
        if not await terminal_bridge.session_exists(session.tmux_session_name, log_missing=False):
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

    # Create daemon
    daemon = TeleClaudeDaemon(str(env_path))

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum: int, _frame: object) -> None:
        """Handle termination signals."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s signal...", sig_name)
        daemon.shutdown_event.set()

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
