"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, TextIO, cast

from dotenv import load_dotenv

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.config import config  # config.py loads .env at import time
from teleclaude.core import terminal_bridge  # Imported for test mocking
from teleclaude.core import (
    command_handlers,
    polling_coordinator,
    session_cleanup,
    voice_message_handler,
)
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents
from teleclaude.core.file_handler import handle_file
from teleclaude.core.models import Session
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_utils import get_output_file_path
from teleclaude.core.voice_message_handler import init_voice_handler
from teleclaude.logging_config import setup_logging
from teleclaude.mcp_server import TeleClaudeMCPServer

# Logging defaults (can be overridden via environment variables)
DEFAULT_LOG_FILE = "/var/log/teleclaude.log"
DEFAULT_LOG_LEVEL = "INFO"

logger = logging.getLogger(__name__)

# Command events that route to handle_command via generic handler
# All events in this set use _handle_command_event → handle_command()
COMMAND_EVENTS = {
    TeleClaudeEvents.NEW_SESSION,
    TeleClaudeEvents.LIST_SESSIONS,
    TeleClaudeEvents.GET_SESSION_DATA,
    TeleClaudeEvents.LIST_PROJECTS,
    TeleClaudeEvents.GET_COMPUTER_INFO,
    TeleClaudeEvents.CD,
    TeleClaudeEvents.KILL,
    TeleClaudeEvents.CANCEL,
    TeleClaudeEvents.CANCEL_2X,
    TeleClaudeEvents.ESCAPE,
    TeleClaudeEvents.ESCAPE_2X,
    TeleClaudeEvents.CTRL,
    TeleClaudeEvents.TAB,
    TeleClaudeEvents.SHIFT_TAB,
    TeleClaudeEvents.BACKSPACE,
    TeleClaudeEvents.ENTER,
    TeleClaudeEvents.KEY_UP,
    TeleClaudeEvents.KEY_DOWN,
    TeleClaudeEvents.KEY_LEFT,
    TeleClaudeEvents.KEY_RIGHT,
    TeleClaudeEvents.RENAME,
    TeleClaudeEvents.CLAUDE,
    TeleClaudeEvents.CLAUDE_RESUME,
}


class DaemonLockError(Exception):
    """Raised when another daemon instance is already running."""


class TeleClaudeDaemon:
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

        # Output file directory (persistent files for download button)
        self.output_dir = Path("workspace")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize unified adapter client (observer pattern - NO daemon reference)
        self.client = AdapterClient()

        # Auto-discover and register event handlers
        for attr_name in dir(TeleClaudeEvents):
            if attr_name.startswith("_"):
                continue

            event_value = getattr(TeleClaudeEvents, attr_name)
            if not isinstance(event_value, str):
                continue

            # Commands use generic handler
            if event_value in COMMAND_EVENTS:
                self.client.on(cast(EventType, event_value), self._handle_command_event)
                logger.debug("Auto-registered command: %s → _handle_command_event", event_value)
            else:
                # Non-commands (message, voice, topic_closed) use specific handlers
                handler_name = f"_handle_{event_value}"
                handler = getattr(self, handler_name, None)

                if handler and callable(handler):
                    self.client.on(cast(EventType, event_value), handler)
                    logger.debug("Auto-registered handler: %s → %s", event_value, handler_name)
                else:
                    logger.debug("No handler for event: %s (skipped)", event_value)

        # Load adapters from config (creates TelegramAdapter, RedisAdapter, etc.)
        self.client._load_adapters()

        # Initialize MCP server (if enabled)
        self.mcp_server: Optional[TeleClaudeMCPServer] = None
        if config.mcp.enabled:
            self.mcp_server = TeleClaudeMCPServer(
                adapter_client=self.client,
                terminal_bridge=terminal_bridge,
            )

        # Shutdown event for graceful termination
        self.shutdown_event = asyncio.Event()

    async def _handle_command_event(self, event: str, context: dict[str, object]) -> object:
        """Generic handler for all command events.

        All commands route to handle_command() with args from context.

        Args:
            event: Command event type (new_session, cd, kill, etc.)
            context: Unified context (all payload + metadata fields)

        Returns:
            Result from command handler
        """
        args_obj = context.get("args", [])
        # Type assertion: args from adapters are always list[str]
        args = list(args_obj) if isinstance(args_obj, list) else []
        return await self.handle_command(event, args, context)

    async def _handle_message(self, _event: str, context: dict[str, object]) -> None:
        """Handler for MESSAGE events - pure business logic (cleanup already done).

        Args:
            _event: Event type (always "message") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        text = context.get("text")

        if not session_id or not text:
            logger.warning("MESSAGE event missing required fields: session_id=%s, text=%s", session_id, text)
            return

        # Auto-reopen if closed
        session = await db.get_session(str(session_id))
        if session and session.closed:
            logger.info(
                "Auto-reopening closed session %s", session_id[:8] if isinstance(session_id, str) else session_id
            )
            await self._reopen_session(session)

        await self.handle_message(str(session_id), str(text), context)

    async def _handle_voice(self, _event: str, context: dict[str, object]) -> None:
        """Handler for VOICE events - pure business logic (cleanup already done).

        Args:
            _event: Event type (always "voice") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        audio_file_path = context.get("file_path")

        if not session_id or not audio_file_path:
            logger.warning(
                "VOICE event missing required fields: session_id=%s, file_path=%s", session_id, audio_file_path
            )
            return

        # Define send_feedback to properly track temporary messages for deletion
        async def send_feedback(sid: str, msg: str, _append: bool) -> Optional[str]:
            """Send feedback message and mark for deletion on next input."""
            message_id = await self.client.send_message(sid, msg, metadata={"parse_mode": None})
            if message_id:
                # Mark feedback message for deletion when next input arrives
                await db.add_pending_deletion(sid, message_id)
            return message_id

        # Handle voice message using utility function
        await voice_message_handler.handle_voice(
            session_id=str(session_id),
            audio_path=str(audio_file_path),
            context=context,
            send_feedback=send_feedback,
            get_output_file=self._get_output_file_path,
        )

    async def _handle_session_closed(self, _event: str, context: dict[str, object]) -> None:
        """Handler for session_closed events - user closed topic.

        Args:
            _event: Event type (always "session_closed") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("session_closed event missing session_id")
            return

        session = await db.get_session(str(session_id))
        if not session:
            logger.warning("Session %s not found for close event", session_id)
            return

        logger.info("Handling session_closed for %s", session_id[:8] if isinstance(session_id, str) else session_id)

        # Kill tmux session (polling will stop automatically when session dies)
        await terminal_bridge.kill_session(session.tmux_session_name)

        # Mark closed in DB
        await db.update_session(str(session_id), closed=True)

    async def _handle_session_reopened(self, _event: str, context: dict[str, object]) -> None:
        """Handler for session_reopened events - user reopened topic.

        Args:
            _event: Event type (always "session_reopened") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("session_reopened event missing session_id")
            return

        session = await db.get_session(str(session_id))
        if not session:
            logger.warning("Session %s not found for reopen event", session_id)
            return

        logger.info("Handling session_reopened for %s", session_id[:8] if isinstance(session_id, str) else session_id)
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

        await terminal_bridge.create_tmux_session(
            name=session.tmux_session_name,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            session_id=session.session_id,
        )

        await db.update_session(session.session_id, closed=False)
        logger.info("Session %s reopened at %s", session.session_id[:8], session.working_directory)

    async def _handle_session_deleted(self, _event: str, context: dict[str, object]) -> None:
        """Handler for session_deleted events (placeholder - not currently emitted).

        Args:
            _event: Event type (always "session_deleted") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        logger.debug("session_deleted event received but not implemented: %s", context)

    async def _handle_working_dir_changed(self, _event: str, context: dict[str, object]) -> None:
        """Handler for working_dir_changed events (placeholder - not currently emitted).

        Args:
            _event: Event type (always "working_dir_changed") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        logger.debug("working_dir_changed event received but not implemented: %s", context)

    async def _handle_file(self, _event: str, context: dict[str, object]) -> None:
        """Handler for FILE events - pure business logic.

        Args:
            _event: Event type (always "file") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        file_path = context.get("file_path")
        filename = context.get("filename")

        if not session_id or not file_path or not filename:
            logger.warning(
                "FILE event missing required fields: session_id=%s, file_path=%s, filename=%s",
                session_id,
                file_path,
                filename,
            )
            return

        async def send_feedback(sid: str, msg: str, _append: bool) -> Optional[str]:
            """Send feedback message and mark for deletion on next input."""
            message_id = await self.client.send_message(sid, msg, metadata={"parse_mode": None})
            if message_id:
                await db.add_pending_deletion(sid, message_id)
            return message_id

        await handle_file(
            session_id=str(session_id),
            file_path=str(file_path),
            filename=str(filename),
            context=context,
            send_feedback=send_feedback,
        )

    async def _handle_system_command(self, _event: str, context: dict[str, object]) -> None:
        """Handler for SYSTEM_COMMAND events.

        System commands are daemon-level operations (deploy, restart, etc.)

        Args:
            _event: Event type (always "system_command") - unused but required by event handler signature
            context: Unified context (all payload + metadata fields)
        """
        command = context.get("command")
        args = context.get("args", {})
        from_computer = context.get("from_computer", "unknown")

        if not command:
            logger.warning("SYSTEM_COMMAND event missing command")
            return

        logger.info("Handling system command '%s' from %s", command, from_computer)

        if command == "deploy":
            args_dict: dict[str, object] = args if isinstance(args, dict) else {}
            await self._handle_deploy(args_dict)
        elif command == "health_check":
            await self._handle_health_check()
        else:
            logger.warning("Unknown system command: %s", command)

    async def _handle_deploy(self, _args: dict[str, object]) -> None:
        """Execute deployment: git pull + restart daemon via service manager."""
        # Get Redis adapter for status updates
        redis_adapter_base = self.client.adapters.get("redis")
        if not redis_adapter_base or not isinstance(redis_adapter_base, RedisAdapter):
            logger.error("Redis adapter not available, cannot update deploy status")
            return

        redis_adapter: RedisAdapter = redis_adapter_base
        status_key = f"system_status:{config.computer.name}:deploy"

        try:
            # 1. Write deploying status
            await redis_adapter.redis.set(
                status_key,
                json.dumps({"status": "deploying", "timestamp": time.time()}),
            )
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
                await redis_adapter.redis.set(
                    status_key,
                    json.dumps({"status": "error", "error": f"git pull failed: {error_msg}"}),
                )
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
                install_stdout, install_stderr = await asyncio.wait_for(install_result.communicate(), timeout=60.0)
            except asyncio.TimeoutError:
                logger.error("Deploy: make install timed out after 60s")
                await redis_adapter.redis.set(
                    status_key,
                    json.dumps({"status": "error", "error": "make install timed out after 60s"}),
                )
                return

            if install_result.returncode != 0:
                error_msg = install_stderr.decode("utf-8")
                logger.error("Deploy: make install failed: %s", error_msg)
                await redis_adapter.redis.set(
                    status_key,
                    json.dumps({"status": "error", "error": f"make install failed: {error_msg}"}),
                )
                return

            install_output = install_stdout.decode("utf-8")
            logger.info("Deploy: make install successful - %s", install_output.strip())

            # 4. Write restarting status
            await redis_adapter.redis.set(
                status_key,
                json.dumps({"status": "restarting", "timestamp": time.time()}),
            )

            # 5. Exit to trigger service manager restart
            # With Restart=on-failure, any non-zero exit triggers restart
            # Use exit code 42 to indicate intentional deploy restart (not a crash)
            logger.info("Deploy: exiting with code 42 to trigger service manager restart")
            os._exit(42)

        except Exception as e:
            logger.error("Deploy failed: %s", e, exc_info=True)
            if redis_adapter and redis_adapter.redis:
                await redis_adapter.redis.set(
                    status_key,
                    json.dumps({"status": "error", "error": str(e)}),
                )

    async def _handle_health_check(self) -> None:
        """Handle health check system command."""
        logger.info("Health check requested")

    def _get_output_file_path(self, session_id: str) -> Path:
        """Get output file path for a session (delegates to session_utils)."""
        return get_output_file_path(session_id)

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
                f"No adapter available for type '{adapter_type}'. " f"Available: {list(self.client.adapters.keys())}"
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
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if not success:
            error_msg_id = await self.client.send_message(session_id, f"Failed to execute command: {command}")
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
        logger.info("Database wired to AdapterClient")

        # Initialize voice handler
        init_voice_handler()
        logger.info("Voice handler initialized")

        # Start all adapters via AdapterClient
        await self.client.start()

        # Check if we just restarted from deployment
        redis_adapter_base = self.client.adapters.get("redis")
        if redis_adapter_base and isinstance(redis_adapter_base, RedisAdapter):
            redis_adapter: RedisAdapter = redis_adapter_base
            if redis_adapter.redis:
                status_key = f"system_status:{config.computer.name}:deploy"
                status_data = await redis_adapter.redis.get(status_key)
                if status_data:
                    try:
                        status = json.loads(status_data.decode("utf-8"))
                        if status.get("status") == "restarting":
                            # We successfully restarted from deployment
                            await redis_adapter.redis.set(
                                status_key,
                                json.dumps({"status": "deployed", "timestamp": time.time(), "pid": os.getpid()}),
                            )
                            logger.info("Deployment complete, daemon restarted successfully (PID: %s)", os.getpid())
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning("Failed to parse deploy status: %s", e)

        # Start MCP server in background task (if enabled)
        if self.mcp_server:
            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            logger.info("MCP server starting in background")

        # Start periodic cleanup task (runs every hour)
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Periodic cleanup task started (72h session lifecycle)")

        # Restore polling for sessions that were active before restart
        await polling_coordinator.restore_active_pollers(
            adapter_client=self.client,
            output_poller=self.output_poller,
            get_output_file=self._get_output_file_path,
        )

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

        # Stop all adapters
        for adapter_name, adapter in self.client.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            await adapter.stop()

        # Close database
        await db.close()

        logger.info("Daemon stopped")

    async def handle_command(self, command: str, args: list[str], context: dict[str, Any]) -> Any:  # type: ignore[explicit-any]  # Adapter-specific context  # pylint: disable=too-many-branches
        """Handle bot commands.

        Args:
            command: Event name from TeleClaudeEvents (e.g., "new_session", "list_projects")
            args: Command arguments
            context: Platform-specific context

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
            return await command_handlers.handle_create_session(context, args, self.client)
        elif command == TeleClaudeEvents.LIST_SESSIONS:
            return await command_handlers.handle_list_sessions(context, self.client)
        elif command == TeleClaudeEvents.LIST_PROJECTS:
            return await command_handlers.handle_list_projects(context, self.client)
        elif command == TeleClaudeEvents.GET_SESSION_DATA:
            return await command_handlers.handle_get_session_data(context, args, self.client)
        elif command == TeleClaudeEvents.GET_COMPUTER_INFO:
            logger.info(">>> BRANCH MATCHED: GET_COMPUTER_INFO")
            logger.info("Calling handle_get_computer_info with context keys: %s", list(context.keys()))
            result = await command_handlers.handle_get_computer_info(context, self.client)
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
        elif command == "resize":
            return await command_handlers.handle_resize_session(context, args, self.client)
        elif command == TeleClaudeEvents.RENAME:
            return await command_handlers.handle_rename_session(context, args, self.client)
        elif command == TeleClaudeEvents.CD:
            return await command_handlers.handle_cd_session(context, args, self.client, self._execute_terminal_command)
        elif command == TeleClaudeEvents.CLAUDE:
            return await command_handlers.handle_claude_session(context, args, self._execute_terminal_command)
        elif command == TeleClaudeEvents.CLAUDE_RESUME:
            return await command_handlers.handle_claude_resume_session(context, self._execute_terminal_command)
        elif command == "exit":
            return await command_handlers.handle_exit_session(context, self.client, self._get_output_file_path)

        return None

    async def handle_message(self, session_id: str, text: str, _context: dict) -> None:  # type: ignore[type-arg]
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
                session_id, "⚠️ This session's terminal was closed externally and has been cleaned up."
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
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if not success:
            logger.error("Failed to send command to session %s", session_id[:8])
            error_msg_id = await self.client.send_message(session_id, "Failed to send command to terminal")
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
        """Periodically clean up inactive sessions (72h lifecycle)."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self._cleanup_inactive_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic cleanup: %s", e)

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
        """Wrapper around polling_coordinator.poll_and_send_output (creates background task).

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            marker_id: Unique marker ID for exit detection (None = no exit marker)
        """
        asyncio.create_task(
            polling_coordinator.poll_and_send_output(
                session_id=session_id,
                tmux_session_name=tmux_session_name,
                output_poller=self.output_poller,
                adapter_client=self.client,  # Use AdapterClient for multi-adapter broadcasting
                get_output_file=self._get_output_file_path,
                marker_id=marker_id,
            )
        )


async def main() -> None:
    """Main entry point."""
    # Find .env file for daemon constructor
    base_dir = Path(__file__).parent.parent
    env_path = base_dir / ".env"

    # Note: .env already loaded at module import time (before config expansion)

    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    log_file = os.getenv("TELECLAUDE_LOG_FILE", DEFAULT_LOG_FILE)
    setup_logging(level=log_level, log_file=log_file)

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
        # Acquire lock to prevent multiple instances
        daemon._acquire_lock()

        # Start daemon
        await daemon.start()

        # Wait for shutdown signal
        await daemon.shutdown_event.wait()

    except DaemonLockError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal...")
    finally:
        try:
            await daemon.stop()
        except Exception as e:
            logger.error("Error during daemon stop: %s", e)
        finally:
            daemon._release_lock()


if __name__ == "__main__":
    asyncio.run(main())
