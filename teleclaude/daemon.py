"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional, TextIO, cast

import uvicorn
from dotenv import load_dotenv

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config  # config.py loads .env at import time
from teleclaude.core import terminal_bridge  # Imported for test mocking
from teleclaude.core import (
    command_handlers,
    polling_coordinator,
    session_lifecycle,
    voice_message_handler,
)
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.voice_message_handler import init_voice_handler
from teleclaude.logging_config import setup_logging
from teleclaude.mcp_server import TeleClaudeMCPServer
from teleclaude.rest_api import TeleClaudeAPI

logger = logging.getLogger(__name__)


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
        self.output_dir = Path("session_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize REST API
        api_port = int(os.getenv("PORT", str(config.rest_api.port)))
        self.rest_api = TeleClaudeAPI(
            bind_address="127.0.0.1",
            port=api_port,
        )

        # Initialize unified adapter client (observer pattern - NO daemon reference)
        self.client = AdapterClient()

        # Define command events (all route to handle_command via generic handler)
        COMMAND_EVENTS = {
            TeleClaudeEvents.NEW_SESSION,
            TeleClaudeEvents.LIST_SESSIONS,
            TeleClaudeEvents.LIST_PROJECTS,
            TeleClaudeEvents.CD,
            TeleClaudeEvents.KILL,
            TeleClaudeEvents.CANCEL,
            TeleClaudeEvents.CANCEL_2X,
            TeleClaudeEvents.ESCAPE,
            TeleClaudeEvents.ESCAPE_2X,
            TeleClaudeEvents.CTRL,
            TeleClaudeEvents.TAB,
            TeleClaudeEvents.SHIFT_TAB,
            TeleClaudeEvents.KEY_UP,
            TeleClaudeEvents.KEY_DOWN,
            TeleClaudeEvents.KEY_LEFT,
            TeleClaudeEvents.KEY_RIGHT,
            TeleClaudeEvents.RENAME,
            TeleClaudeEvents.CLAUDE,
            TeleClaudeEvents.CLAUDE_RESUME,
        }

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

    async def _handle_command_event(self, event: str, context: dict[str, object]) -> None:
        """Generic handler for all command events.

        All commands route to handle_command() with args from context.

        Args:
            event: Command event type (new_session, cd, kill, etc.)
            context: Unified context (all payload + metadata fields)
        """
        args_obj = context.get("args", [])
        # Type assertion: args from adapters are always list[str]
        args = list(args_obj) if isinstance(args_obj, list) else []
        await self.handle_command(event, args, context)

    async def _handle_message(self, event: str, context: dict[str, object]) -> None:
        """Handler for MESSAGE events - pure business logic (cleanup already done).

        Args:
            event: Event type (always "message")
            context: Unified context (all payload + metadata fields)
        """
        session_id = context.get("session_id")
        text = context.get("text")

        if not session_id or not text:
            logger.warning("MESSAGE event missing required fields: session_id=%s, text=%s", session_id, text)
            return

        await self.handle_message(str(session_id), str(text), context)

    async def _handle_voice(self, event: str, context: dict[str, object]) -> None:
        """Handler for VOICE events - pure business logic (cleanup already done).

        Args:
            event: Event type (always "voice")
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
        async def send_feedback(sid: str, msg: str, append: bool) -> Optional[str]:
            """Send feedback message and mark for deletion on next input."""
            message_id = await self.client.send_message(sid, msg)
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
            get_output_file=self._get_output_file,
        )

    def _get_output_file(self, session_id: str) -> Path:
        """Get output file path for a session."""
        return self.output_dir / f"{session_id[:8]}.txt"

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
        append_exit_marker: bool = True,
        message_id: Optional[str] = None,
    ) -> bool:
        """Execute command in terminal and start polling if needed.

        Args:
            session_id: Session ID
            command: Command to execute
            append_exit_marker: Whether to append exit marker (default: True)
            message_id: Message ID to cleanup (optional)

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

        # Send command
        success = await terminal_bridge.send_keys(
            session.tmux_session_name,
            command,
            shell=config.computer.default_shell,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=append_exit_marker,
        )

        if not success:
            await self.client.send_message(session_id, f"Failed to execute command: {command}")
            logger.error("Failed to execute command in session %s: %s", session_id[:8], command)
            return False

        # Update activity
        await db.update_last_activity(session_id)

        # NOTE: Message cleanup now handled by TelegramAdapter pre/post handlers
        # - POST handler tracks message_id for deletion
        # - PRE handler deletes on NEXT user input (better UX - failed commands stay visible)

        # Start polling if exit marker was appended
        if append_exit_marker:
            await self._poll_and_send_output(session_id, session.tmux_session_name)

        logger.info("Executed command in session %s: %s", session_id[:8], command)
        return True

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting TeleClaude daemon...")

        # Initialize database
        await db.initialize()
        logger.info("Database initialized")

        # Initialize voice handler
        init_voice_handler()
        logger.info("Voice handler initialized")

        # Start all adapters via AdapterClient
        await self.client.start()

        # Start MCP server in background task (if enabled)
        if self.mcp_server:
            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            logger.info("MCP server starting in background")

        # Start FastAPI REST API in background task
        uvicorn_config = uvicorn.Config(
            self.rest_api.get_asgi_app(),
            host=self.rest_api.bind_address,
            port=self.rest_api.port,
            log_level="info",
            access_log=False,  # Reduce noise
        )
        self.uvicorn_server = uvicorn.Server(uvicorn_config)
        self.api_task = asyncio.create_task(self.uvicorn_server.serve())
        logger.info("REST API started on http://%s:%s", self.rest_api.bind_address, self.rest_api.port)

        # Start periodic cleanup task (runs every hour)
        self.cleanup_task = asyncio.create_task(session_lifecycle.periodic_cleanup(db, config))
        logger.info("Periodic cleanup task started (72h session lifecycle)")

        # Restore polling for sessions that were active before restart
        await polling_coordinator.restore_active_pollers(
            adapter_client=self.client,
            output_poller=self.output_poller,
            get_output_file=self._get_output_file,
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

        # Stop REST API
        if hasattr(self, "uvicorn_server"):
            self.uvicorn_server.should_exit = True
            await self.api_task

        # Close database
        await db.close()

        logger.info("Daemon stopped")

    async def handle_command(self, command: str, args: list[str], context: dict[str, Any]) -> None:  # type: ignore[explicit-any]  # Adapter-specific context
        """Handle bot commands.

        Args:
            command: Event name from TeleClaudeEvents (e.g., "new_session", "list_projects")
            args: Command arguments
            context: Platform-specific context
        """
        logger.info("Command received: %s %s", command, args)

        if command == TeleClaudeEvents.NEW_SESSION:
            await command_handlers.handle_create_session(context, args, self.client)
        elif command == TeleClaudeEvents.LIST_SESSIONS:
            await command_handlers.handle_list_sessions(context, self.client)
        elif command == TeleClaudeEvents.LIST_PROJECTS:
            await command_handlers.handle_list_projects(context, self.client)
        elif command == TeleClaudeEvents.CANCEL:
            await command_handlers.handle_cancel_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.CANCEL_2X:
            await command_handlers.handle_cancel_command(context, self.client, self._poll_and_send_output, double=True)
        elif command == TeleClaudeEvents.KILL:
            await command_handlers.handle_kill_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.ESCAPE:
            await command_handlers.handle_escape_command(context, args, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.ESCAPE_2X:
            await command_handlers.handle_escape_command(
                context,
                args,
                self.client,
                self._poll_and_send_output,
                double=True,
            )
        elif command == TeleClaudeEvents.CTRL:
            await command_handlers.handle_ctrl_command(context, args, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.TAB:
            await command_handlers.handle_tab_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.SHIFT_TAB:
            await command_handlers.handle_shift_tab_command(context, self.client, self._poll_and_send_output)
        elif command == TeleClaudeEvents.KEY_UP:
            await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "up"
            )
        elif command == TeleClaudeEvents.KEY_DOWN:
            await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "down"
            )
        elif command == TeleClaudeEvents.KEY_LEFT:
            await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "left"
            )
        elif command == TeleClaudeEvents.KEY_RIGHT:
            await command_handlers.handle_arrow_key_command(
                context, args, self.client, self._poll_and_send_output, "right"
            )
        elif command == "resize":
            await command_handlers.handle_resize_session(context, args, self.client)
        elif command == TeleClaudeEvents.RENAME:
            await command_handlers.handle_rename_session(context, args, self.client)
        elif command == TeleClaudeEvents.CD:
            await command_handlers.handle_cd_session(context, args, self.client, self._execute_terminal_command)
        elif command == TeleClaudeEvents.CLAUDE:
            await command_handlers.handle_claude_session(context, self._execute_terminal_command)
        elif command == TeleClaudeEvents.CLAUDE_RESUME:
            await command_handlers.handle_claude_resume_session(context, self._execute_terminal_command)
        elif command == "exit":
            await command_handlers.handle_exit_session(context, self.client, self._get_output_file)

    async def handle_message(self, session_id: str, text: str, context: dict[str, Any]) -> None:  # type: ignore[explicit-any]  # Adapter-specific context
        """Handle incoming text messages (commands for terminal)."""
        logger.debug("Message for session %s: %s...", session_id[:8], text[:50])

        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Strip leading // and replace with / (Telegram workaround - only at start of input)
        if text.startswith("//"):
            text = "/" + text[2:]
            logger.debug("Stripped leading // from user input, result: %s", text[:50])

        # Parse terminal size (e.g., "80x24" -> cols=80, rows=24)
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Check if a process is currently running (polling active)
        ux_state = await db.get_ux_state(session_id)
        is_process_running = ux_state.polling_active

        # Send command to terminal (will create fresh session if needed)
        # Only append exit marker if starting a NEW command, not sending input to running process
        success = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
            shell=config.computer.default_shell,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=not is_process_running,
        )

        if not success:
            logger.error("Failed to send command to session %s", session_id[:8])
            await self.client.send_message(session_id, "Failed to send command to terminal")
            return

        # Update activity
        await db.update_last_activity(session_id)

        # Start new poll if process not running, otherwise existing poll continues
        if not is_process_running:
            await self._poll_and_send_output(session_id, session.tmux_session_name)
        else:
            logger.debug(
                "Input sent to running process in session %s, existing poll will capture output", session_id[:8]
            )

    async def handle_topic_closed(self, session_id: str, context: dict[str, Any]) -> None:  # type: ignore[explicit-any]  # Adapter-specific context
        """Handle topic/channel closure event."""
        logger.info("Topic closed for session %s, closing session and tmux", session_id[:8])

        # Get session
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found during topic closure", session_id)
            return

        # Kill the tmux session
        tmux_session_name = session.tmux_session_name
        logger.info("Killing tmux session: %s", tmux_session_name)
        success = await terminal_bridge.kill_session(tmux_session_name)
        if not success:
            logger.warning("Failed to kill tmux session %s", tmux_session_name)

        # Mark session as closed in database
        await db.update_session(session_id, closed=True)
        logger.info("Session %s marked as closed", session_id[:8])

    async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None:
        """Wrapper around polling_coordinator.poll_and_send_output (creates background task)."""
        asyncio.create_task(
            polling_coordinator.poll_and_send_output(
                session_id=session_id,
                tmux_session_name=tmux_session_name,
                output_poller=self.output_poller,
                adapter_client=self.client,  # Use AdapterClient for multi-adapter broadcasting
                get_output_file=self._get_output_file,
            )
        )


async def main() -> None:
    """Main entry point."""
    # Find .env file for daemon constructor
    base_dir = Path(__file__).parent.parent
    env_path = base_dir / ".env"

    # Note: .env already loaded at module import time (before config expansion)

    # Setup logging (config already loaded at module level)
    setup_logging(level=str(config.logging.level), log_file=str(config.logging.file))

    # Create daemon
    daemon = TeleClaudeDaemon(str(env_path))

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum: int, frame: object) -> None:
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
