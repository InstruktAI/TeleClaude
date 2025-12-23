"""TeleClaude main daemon."""

import asyncio
import atexit
import base64
import fcntl
import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, TextIO, cast

from dotenv import load_dotenv
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config  # config.py loads .env at import time
from teleclaude.core import (
    command_handlers,
    polling_coordinator,
    session_cleanup,
    terminal_bridge,  # Imported for test mocking
    voice_assignment,
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
from teleclaude.core.models import MessageMetadata, Session, SessionCommandContext
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_listeners import cleanup_caller_listeners, get_listeners, pop_listeners
from teleclaude.core.session_utils import get_output_file
from teleclaude.core.summarizer import summarize
from teleclaude.core.terminal_bridge import send_keys
from teleclaude.core.voice_message_handler import init_voice_handler
from teleclaude.logging_config import setup_logging
from teleclaude.mcp_server import TeleClaudeMCPServer

# Logging defaults (can be overridden via environment variables)
DEFAULT_LOG_LEVEL = "INFO"

# Startup retry configuration
STARTUP_MAX_RETRIES = 3
STARTUP_RETRY_DELAYS = [10, 20, 40]  # Exponential backoff in seconds

logger = get_logger(__name__)


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
        # Auto-reopen if closed
        session = await db.get_session(context.session_id)
        if session and session.closed:
            logger.info("Auto-reopening closed session %s", context.session_id[:8])
            await self._reopen_session(session)

        # Pass typed context directly
        await self.handle_message(context.session_id, context.text, context)

    async def _handle_voice(self, _event: str, context: VoiceEventContext) -> None:
        """Handler for VOICE events - pure business logic (cleanup already done).

        Args:
            _event: Event type (always "voice") - unused but required by event handler signature
            context: Voice event context (Pydantic)
        """
        # Handle voice message using utility function
        await voice_message_handler.handle_voice(
            session_id=context.session_id,
            audio_path=context.file_path,
            context=context,
            send_feedback=self._send_feedback_callback,  # type: ignore[arg-type]
        )

    async def _handle_session_closed(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_closed events - user closed topic.

        Args:
            _event: Event type (always "session_closed") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context

        session = await db.get_session(ctx.session_id)
        if not session:
            logger.warning("Session %s not found for close event", ctx.session_id[:8])
            return

        logger.info("Handling session_closed for %s", ctx.session_id[:8])

        # Kill tmux session (polling will stop automatically when session dies)
        await terminal_bridge.kill_session(session.tmux_session_name)

        # Mark closed in DB
        await db.update_session(ctx.session_id, closed=True)

        # Clean up session listeners:
        # 1. Remove listeners where this session was the target (nobody listening to it anymore)
        target_listeners = pop_listeners(ctx.session_id)
        if target_listeners:
            logger.debug(
                "Cleaned up %d listener(s) for closed target session %s",
                len(target_listeners),
                ctx.session_id[:8],
            )

        # 2. Remove listeners where this session was the caller (can't receive notifications anymore)
        caller_count = cleanup_caller_listeners(ctx.session_id)
        if caller_count:
            logger.debug(
                "Cleaned up %d listener(s) registered by closed caller session %s",
                caller_count,
                ctx.session_id[:8],
            )

        # Delete output file
        output_file = self._get_output_file_path(ctx.session_id)
        if output_file.exists():
            try:
                output_file.unlink()
                logger.debug("Deleted output file for closed session %s", ctx.session_id[:8])
            except Exception as e:
                logger.warning("Failed to delete output file for closed session %s: %s", ctx.session_id[:8], e)

    async def _handle_session_reopened(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_reopened events - user reopened topic.

        Args:
            _event: Event type (always "session_reopened") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context

        session = await db.get_session(ctx.session_id)
        if not session:
            logger.warning("Session %s not found for reopen event", ctx.session_id[:8])
            return

        logger.info("Handling session_reopened for %s", ctx.session_id[:8])
        await self._reopen_session(session)

    async def _reopen_session(self, session: Session) -> None:
        """Recreate tmux at saved working directory and mark active."""
        # Parse terminal size (format: "WIDTHxHEIGHT")
        cols, rows = 120, 40
        if session.terminal_size:
            try:
                width, height = session.terminal_size.split("x")
                cols, rows = int(width), int(height)
            except (ValueError, AttributeError):
                pass

        # Restore voice env vars from DB if available
        # Lookup by native_session_id first (persists across tmux restarts), then by session_id
        voice_env_vars = None
        ux_state = await db.get_ux_state(session.session_id)
        voice = None
        if ux_state.native_session_id:
            voice = await db.get_voice(ux_state.native_session_id)
        if not voice:
            voice = await db.get_voice(session.session_id)
        if voice:
            voice_env_vars = voice_assignment.get_voice_env_vars(voice)
            logger.debug("Restored voice '%s' for session %s", voice.name, session.session_id[:8])

        await terminal_bridge.create_tmux_session(
            name=session.tmux_session_name,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            session_id=session.session_id,
            env_vars=voice_env_vars,
        )

        await db.update_session(session.session_id, closed=False)
        logger.info("Session %s reopened at %s", session.session_id[:8], session.working_directory)

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
            send_feedback=self._send_feedback_callback,  # type: ignore[arg-type]
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

        try:
            ux_state = await db.get_ux_state(session_id)
            if not ux_state.active_agent:
                raise ValueError(f"Session {session_id[:8]} missing active_agent metadata")

            agent_name = AgentName.from_str(ux_state.active_agent)
            title, summary = await summarize(agent_name, payload.transcript_path)

            payload.summary = summary
            payload.title = title
            payload.raw["summary"] = payload.summary
            payload.raw["title"] = payload.title

            if payload.title:
                await self._update_session_title(session_id, payload.title)

            session = await db.get_session(session_id)
            if not session:
                raise ValueError(f"Summary feedback requires active session: {session_id}")
            await self.client.send_feedback(session, summary, MessageMetadata(adapter_type="internal"))

            # Dispatch to coordinator
            await self.agent_coordinator.handle_stop(context)

        except Exception as e:
            logger.error("Failed to process agent stop event for session %s: %s", session_id[:8], e)
            # Try to report error to user
            try:
                session = await db.get_session(session_id)
                if session:
                    await self.client.send_feedback(
                        session,
                        f"Error processing session summary: {e}",
                        MessageMetadata(adapter_type="internal"),
                    )
            except Exception:
                pass

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
        await self.client.send_feedback(session, message, MessageMetadata(adapter_type="internal"))

    async def _update_session_title(self, session_id: str, title: str) -> None:
        """Update session title in DB and UI."""
        session = await db.get_session(session_id)
        if not session:
            return

        import re

        if not re.search(r"New session( \(\d+\))?$", session.title):
            return

        title_pattern = r"^(\$\w+\[[^\]]+\] - ).*$"
        match = re.match(title_pattern, session.title)

        if match:
            new_title = f"{match.group(1)}{title}"
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

        async def update_status(payload: dict[str, object]) -> None:
            await redis_client.set(status_key, json.dumps(payload))

        try:
            # 1. Write deploying status
            deploying_payload: dict[str, object] = {"status": "deploying", "timestamp": time.time()}
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
                git_error_payload: dict[str, object] = {
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
                timeout_payload: dict[str, object] = {
                    "status": "error",
                    "error": "make install timed out after 60s",
                }
                await update_status(timeout_payload)
                return

            if install_result.returncode != 0:
                error_msg = install_stderr.decode("utf-8")
                logger.error("Deploy: make install failed: %s", error_msg)
                install_error_payload: dict[str, object] = {
                    "status": "error",
                    "error": f"make install failed: {error_msg}",
                }
                await update_status(install_error_payload)
                return

            install_output = install_stdout.decode("utf-8")
            logger.info("Deploy: make install successful - %s", install_output.strip())

            # 4. Write restarting status
            restarting_payload: dict[str, object] = {"status": "restarting", "timestamp": time.time()}
            await update_status(restarting_payload)

            # 5. Exit to trigger service manager restart
            # With Restart=on-failure, any non-zero exit triggers restart
            # Use exit code 42 to indicate intentional deploy restart (not a crash)
            logger.info("Deploy: exiting with code 42 to trigger service manager restart")
            os._exit(42)

        except Exception as e:
            logger.error("Deploy failed: %s", e, exc_info=True)
            exception_payload: dict[str, object] = {"status": "error", "error": str(e)}
            await update_status(exception_payload)

    async def _handle_health_check(self) -> None:
        """Handle health check system command."""
        logger.info("Health check requested")

    async def _handle_stop_notification(self, _event: str, context: SessionCommandContext) -> None:
        """Handle stop_notification event - forwarded stop event from remote computer.

        When a remote session (AI-to-AI) stops, the target computer forwards the stop
        event to the initiator's computer so the listener can fire.

        Args:
            _event: Event type (always "stop_notification")
            context: Session command context - session_id is in args[0], not context.session_id
        """
        # The session_id is passed as command argument: "/stop_notification {session_id} {computer} [title_b64]"
        # It's in args, not context.session_id (which is empty for forwarded commands)
        if not context.args:
            logger.warning("stop_notification received without session_id argument")
            return
        target_session_id = context.args[0]
        # Second arg is optional source computer name (for actionable notifications)
        source_computer = context.args[1] if len(context.args) > 1 else "remote"
        # Third arg is optional base64-encoded title from stop payload
        title: str | None = None
        if len(context.args) > 2:
            try:
                title = base64.b64decode(context.args[2]).decode()
            except Exception:
                pass  # Invalid base64, ignore

        logger.info(
            "Received stop_notification for remote session %s from %s (title: %s)",
            target_session_id[:8],
            source_computer,
            title[:30] if title else "none",
        )

        # Get listeners (don't pop - session is still active, Claude just finished its turn)
        # Listeners are only removed when session is closed (in _handle_session_closed)
        listeners = get_listeners(target_session_id)
        if not listeners:
            logger.debug("No listeners for remote session %s", target_session_id[:8])
            return

        for listener in listeners:
            # Build actionable notification message with exact command to run
            # Note: "Stop" means Claude finished its turn, not that the session ended
            # Include title if available for richer context
            title_part = f' "{title}"' if title else ""
            notification = (
                f"Session {target_session_id[:8]} on {source_computer}{title_part} finished its turn. "
                f"Retrieve results: teleclaude__get_session_data("
                f'computer="{source_computer}", session_id="{target_session_id}")'
            )

            # Inject into caller's tmux session
            success, error = await send_keys(
                session_name=listener.caller_tmux_session,
                text=notification,
                send_enter=True,
            )

            if success:
                logger.info(
                    "Notified caller %s about remote session %s completion",
                    listener.caller_session_id[:8],
                    target_session_id[:8],
                )
            else:
                logger.warning(
                    "Failed to notify caller %s: %s",
                    listener.caller_session_id[:8],
                    error,
                )

    async def _handle_input_notification(self, _event: str, context: SessionCommandContext) -> None:
        """Handle input_notification event - forwarded input request from remote computer.

        When a remote session (AI-to-AI) asks a question via AskUserQuestion or similar,
        the target computer forwards the notification so the caller can respond.

        Unlike stop_notification, this does NOT pop listeners - the session is still
        active and waiting for a response.

        Args:
            _event: Event type (always "input_notification")
            context: Session command context - session_id is in args[0], not context.session_id
        """
        # Command format: "/input_notification {session_id} {computer} {message_b64}"
        if len(context.args) < 3:
            logger.warning("input_notification received with insufficient arguments: %s", context.args)
            return

        target_session_id = context.args[0]
        source_computer = context.args[1]

        # Decode base64 message
        try:
            message = base64.b64decode(context.args[2]).decode()
        except Exception as e:
            logger.warning("Failed to decode input_notification message: %s", e)
            return

        logger.info(
            "Received input_notification for remote session %s from %s: %s",
            target_session_id[:8],
            source_computer,
            message[:50],
        )

        # Get listeners (don't pop - session is still active)
        listeners = get_listeners(target_session_id)
        if not listeners:
            logger.debug("No listeners for remote session %s", target_session_id[:8])
            return

        for listener in listeners:
            # Build actionable notification message with exact command to respond
            notification = (
                f"Session {target_session_id[:8]} on {source_computer} needs input: {message} "
                f"Use teleclaude__send_message("
                f'computer="{source_computer}", session_id="{target_session_id}", '
                f'message="your response") to respond.'
            )

            # Inject into caller's tmux session
            success, error = await send_keys(
                session_name=listener.caller_tmux_session,
                text=notification,
                send_enter=True,
            )

            if success:
                logger.info(
                    "Forwarded input request from %s to listener %s",
                    target_session_id[:8],
                    listener.caller_session_id[:8],
                )
            else:
                logger.warning(
                    "Failed to forward input request to listener %s: %s",
                    listener.caller_session_id[:8],
                    error,
                )

    def _get_output_file_path(self, session_id: str) -> Path:
        """Get output file path for a session (delegates to session_utils)."""
        return get_output_file(session_id)

    async def _send_feedback_callback(
        self, sid: str, msg: str, metadata: Optional[dict[str, object]] = None
    ) -> Optional[str]:
        """Adapter callback for handlers that need send_feedback signature.

        Wraps AdapterClient.send_feedback to match handler signature.

        Args:
            sid: Session ID
            msg: Feedback message
            metadata: Optional adapter-specific metadata

        Returns:
            message_id if sent, None otherwise
        """
        session = await db.get_session(sid)
        if not session:
            logger.warning("Session %s not found for feedback", sid[:8])
            return None
        return await self.client.send_feedback(session, msg, metadata)  # type: ignore[arg-type]

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

        Exit markers are automatically appended based on shell readiness.

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

        # Get terminal size
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Send command (automatic exit marker decision based on shell readiness)
        # Returns (success, marker_id) tuple
        success, marker_id = await terminal_bridge.send_keys(
            session.tmux_session_name,
            command,
            session_id=session.session_id,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if not success:
            error_msg_id = await self.client.send_message(
                session, f"Failed to execute command: {command}", MessageMetadata()
            )
            if error_msg_id:
                await db.add_pending_deletion(session_id, error_msg_id)
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
            await self._poll_and_send_output(session_id, session.tmux_session_name, marker_id)

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
            logger.info("MCP server starting in background")
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

        # Start session watcher
        await self.codex_watcher.start()
        logger.info("Session watcher started")

        logger.info("TeleClaude is running. Press Ctrl+C to stop.")

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping TeleClaude daemon...")

        # Stop MCP server task
        if hasattr(self, "mcp_task"):
            self.mcp_task.cancel()
            try:
                await self.mcp_task
            except asyncio.CancelledError:
                pass
            logger.info("MCP server stopped")

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
        logger.info("Command received: %s %s", command, args)
        logger.info("Command type: %s, value repr: %r", type(command).__name__, command)
        logger.info(
            "Checking against GET_COMPUTER_INFO: %r (match: %s)",
            TeleClaudeEvents.GET_COMPUTER_INFO,
            command == TeleClaudeEvents.GET_COMPUTER_INFO,
        )

        if command == TeleClaudeEvents.NEW_SESSION:
            result = await command_handlers.handle_create_session(context, args, metadata, self.client)

            # Handle auto_command if specified (e.g., start Claude after session creation)
            if metadata.auto_command and result.get("session_id"):
                session_id = result["session_id"]
                auto_context = CommandEventContext(session_id=session_id, args=[])

                # Parse auto_command (e.g., "agent claude --flag")
                cmd_name, auto_args = parse_command_string(metadata.auto_command)

                if cmd_name == TeleClaudeEvents.AGENT_START and auto_args:
                    agent_name = auto_args.pop(0)  # First arg is agent name
                    await command_handlers.handle_agent_start(
                        auto_context, agent_name, auto_args, self.client, self._execute_terminal_command
                    )
                elif cmd_name == TeleClaudeEvents.AGENT_RESUME and auto_args:
                    agent_name = auto_args.pop(0)
                    await command_handlers.handle_agent_resume(
                        auto_context, agent_name, auto_args, self.client, self._execute_terminal_command
                    )
                else:
                    logger.warning("Unknown or malformed auto_command: %s", metadata.auto_command)

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
            return await command_handlers.handle_cancel_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.CANCEL_2X:
            return await command_handlers.handle_cancel_command(
                context, self.client, self._poll_and_send_output, double=True
            )
        elif command == TeleClaudeEvents.KILL:
            return await command_handlers.handle_kill_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.ESCAPE:
            return await command_handlers.handle_escape_command(context, args, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.ESCAPE_2X:
            return await command_handlers.handle_escape_command(
                context,
                args,
                self.client,
                self._poll_and_send_output,
                double=True,
            )
        elif command == TeleClaudeEvents.CTRL:
            return await command_handlers.handle_ctrl_command(context, args, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.TAB:
            return await command_handlers.handle_tab_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.SHIFT_TAB:
            return await command_handlers.handle_shift_tab_command(
                context, args, self.client, self._poll_and_send_output
            )
        elif command == TeleClaudeEvents.BACKSPACE:
            return await command_handlers.handle_backspace_command(
                context, args, self.client, self._poll_and_send_output
            )
        elif command == TeleClaudeEvents.ENTER:
            return await command_handlers.handle_enter_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.KEY_UP:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "up"
            )
        elif command == TeleClaudeEvents.KEY_DOWN:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "down"
            )
        elif command == TeleClaudeEvents.KEY_LEFT:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "left"
            )
        elif command == TeleClaudeEvents.KEY_RIGHT:
            return await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "right"
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
            warning_msg_id = await self.client.send_message(
                session,
                "⚠️ This session's terminal was closed externally and has been cleaned up.",
                MessageMetadata(),
            )
            if warning_msg_id:
                await db.add_pending_deletion(session_id, warning_msg_id)
            return

        # Parse terminal size (e.g., "80x24" -> cols=80, rows=24)
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Send command to terminal (will create fresh session if needed)
        # Automatic exit marker decision based on shell readiness
        # Returns (success, marker_id) tuple
        success, marker_id = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
            session_id=session.session_id,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if not success:
            logger.error("Failed to send command to session %s", session_id[:8])
            error_msg_id = await self.client.send_message(
                session, "Failed to send command to terminal", MessageMetadata()
            )
            if error_msg_id:
                await db.add_pending_deletion(session_id, error_msg_id)
            return

        # Update activity
        await db.update_last_activity(session_id)

        # Start polling with marker_id for exit detection
        # send_keys() already decided whether to append marker based on shell readiness
        await self._poll_and_send_output(session_id, session.tmux_session_name, marker_id=marker_id)
        logger.debug("Started polling for session %s with marker_id=%s", session_id[:8], marker_id)

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up inactive sessions (72h lifecycle) and orphaned tmux sessions."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour

                # Clean up sessions inactive for 72+ hours
                await self._cleanup_inactive_sessions()

                # Clean up orphaned sessions (tmux gone but DB says active)
                await session_cleanup.cleanup_all_stale_sessions(self.client)

                # Clean up orphan tmux sessions (tmux exists but no DB entry)
                await session_cleanup.cleanup_orphan_tmux_sessions()

                # Clean up orphan workspace directories (workspace exists but no DB entry)
                await session_cleanup.cleanup_orphan_workspaces()

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
                sessions = await db.get_active_sessions()
                for session in sessions:
                    if session.closed:
                        continue
                    if not await terminal_bridge.session_exists(session.tmux_session_name, log_missing=False):
                        continue
                    if not await terminal_bridge.is_process_running(session.tmux_session_name):
                        continue
                    if await polling_coordinator.is_polling(session.session_id):
                        continue

                    await polling_coordinator.schedule_polling(
                        session_id=session.session_id,
                        tmux_session_name=session.tmux_session_name,
                        output_poller=self.output_poller,
                        adapter_client=self.client,
                        get_output_file=self._get_output_file_path,
                        marker_id=None,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in poller watch loop: %s", e)
            await asyncio.sleep(1.0)

    async def _cleanup_inactive_sessions(self) -> None:
        """Clean up sessions inactive for 72+ hours."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=72)
            sessions = await db.list_sessions()

            for session in sessions:
                if session.closed:
                    continue

                # Check last_activity timestamp
                if not session.last_activity:
                    logger.warning("No last_activity for session %s", session.session_id[:8])
                    continue

                if session.last_activity < cutoff_time:
                    logger.info(
                        "Cleaning up inactive session %s (inactive for %s)",
                        session.session_id[:8],
                        datetime.now() - session.last_activity,
                    )

                    # Kill tmux session
                    await terminal_bridge.kill_session(session.tmux_session_name)

                    # Mark as closed
                    await db.update_session(session.session_id, closed=True)

                    logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

        except Exception as e:
            logger.error("Error cleaning up inactive sessions: %s", e)

    async def _poll_and_send_output(
        self, session_id: str, tmux_session_name: str, marker_id: Optional[str] = None
    ) -> None:
        """Wrapper around polling_coordinator.schedule_polling (creates background task).

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            marker_id: Unique marker ID for exit detection (None = no exit marker)
        """
        await polling_coordinator.schedule_polling(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            output_poller=self.output_poller,
            adapter_client=self.client,  # Use AdapterClient for multi-adapter broadcasting
            get_output_file=self._get_output_file_path,
            marker_id=marker_id,
        )


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
