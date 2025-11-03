"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import json
import logging
import os
import shlex
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

import yaml
from dotenv import load_dotenv

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.output_message_manager import OutputMessageManager
from teleclaude.core.output_poller import (
    IdleDetected,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge
from teleclaude.core.voice_handler import VoiceHandler
from teleclaude.logging_config import setup_logging
from teleclaude.rest_api import TeleClaudeAPI
from teleclaude.utils import expand_env_vars

logger = logging.getLogger(__name__)


class DaemonLockError(Exception):
    """Raised when another daemon instance is already running."""


class TeleClaudeDaemon:
    """Main TeleClaude daemon that coordinates all components."""

    def __init__(self, config_path: str, env_path: str):
        """Initialize daemon.

        Args:
            config_path: Path to config.yml
            env_path: Path to .env file
        """
        # Load environment variables
        load_dotenv(env_path)

        # Load config
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # Expand environment variables in config
        self.config = expand_env_vars(self.config)

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: Optional[TextIO] = None  # Will hold the locked file handle

        # Initialize core components
        db_path = os.path.expanduser(self.config["database"]["path"])
        self.session_manager = SessionManager(db_path)
        self.terminal = TerminalBridge(self.config)
        self.message_manager = OutputMessageManager(self.config, self.session_manager)
        self.voice_handler = VoiceHandler()
        self.output_poller = OutputPoller(self.config, self.terminal, self.session_manager)

        # Adapter registry - stores all active adapters
        self.adapters: Dict[str, BaseAdapter] = {}

        # Primary adapter (for commands in "General" topic) - first adapter wins
        self.primary_adapter: Optional[BaseAdapter] = None

        # Track sessions with active polling (to delete user messages sent during polling)
        self.active_polling_sessions: set[str] = set()  # session_ids with processes currently running
        # Maps session_id -> whether exit marker was appended to the command
        self.exit_marker_appended: dict[str, bool] = {}
        self.idle_notifications: dict[str, str] = {}  # session_id -> notification_message_id

        # Output file directory (persistent files for download button)
        self.output_dir = Path("session_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize REST API
        api_port = int(os.getenv("PORT", self.config.get("rest_api", {}).get("port", 6666)))
        self.rest_api = TeleClaudeAPI(
            session_manager=self.session_manager,
            terminal_bridge=self.terminal,
            bind_address="127.0.0.1",
            port=api_port,
        )

        # Load adapters from config
        self._load_adapters()

        # For backward compatibility (temporary - will be removed after full migration)
        # This allows existing code to use self.telegram during migration
        if "telegram" in self.adapters:
            self.telegram = self.adapters["telegram"]

        # Shutdown event for graceful termination
        self.shutdown_event = asyncio.Event()

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

    def _load_adapters(self) -> None:
        """Load and initialize adapters from config.

        Adapters are loaded in order from config. First adapter becomes primary.
        """
        # Load Telegram adapter if configured
        if "telegram" in self.config.get("adapters", {}) or os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram_config = {
                "bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
                "supergroup_id": int(os.getenv("TELEGRAM_SUPERGROUP_ID")),
                "user_whitelist": [int(uid.strip()) for uid in os.getenv("TELEGRAM_USER_IDS", "").split(",")],
                "trusted_dirs": self.config.get("computer", {}).get("trustedDirs", []),
            }

            self.adapters["telegram"] = TelegramAdapter(telegram_config, self.session_manager, self)

            # Register callbacks
            self.adapters["telegram"].on_command(self.handle_command)
            self.adapters["telegram"].on_message(self.handle_message)
            self.adapters["telegram"].on_voice(self.handle_voice)
            self.adapters["telegram"].on_topic_closed(self.handle_topic_closed)

            # Set as primary if first adapter
            if not self.primary_adapter:
                self.primary_adapter = self.adapters["telegram"]

            logger.info("Loaded Telegram adapter")

        # TODO: Load Slack adapter if configured
        # if "slack" in self.config.get("adapters", {}):
        #     slack_config = {...}
        #     self.adapters["slack"] = SlackAdapter(slack_config, self.session_manager)
        #     ...

        # TODO: Load REST adapter if configured
        # Always available for programmatic access

        if not self.adapters:
            raise ValueError("No adapters configured - check config.yml and .env")

        logger.info("Loaded %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

    async def _get_adapter_for_session(self, session_id: str) -> BaseAdapter:
        """Get the adapter responsible for a session.

        Args:
            session_id: Session ID

        Returns:
            BaseAdapter instance

        Raises:
            ValueError: If session not found or no adapter for session's type
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        adapter = self.adapters.get(session.adapter_type)
        if not adapter:
            raise ValueError(
                f"No adapter available for type '{session.adapter_type}'. "
                f"Available adapters: {list(self.adapters.keys())}"
            )

        return adapter

    def _get_adapter_by_type(self, adapter_type: str) -> BaseAdapter:
        """Get adapter by type.

        Args:
            adapter_type: Adapter type name

        Returns:
            BaseAdapter instance

        Raises:
            ValueError: If adapter type not loaded
        """
        adapter = self.adapters.get(adapter_type)
        if not adapter:
            raise ValueError(
                f"No adapter available for type '{adapter_type}'. " f"Available: {list(self.adapters.keys())}"
            )
        return adapter

    async def _execute_terminal_command(
        self,
        session_id: str,
        command: str,
        append_exit_marker: bool = True,
    ) -> bool:
        """Execute command in terminal and start polling if needed.

        Handles the common pattern of:
        1. Getting session
        2. Calling terminal.send_keys
        3. Storing exit_marker_appended
        4. Starting polling loop
        5. Sending error messages on failure

        Args:
            session_id: Session ID
            command: Command to execute
            append_exit_marker: Whether to append exit marker (default: True)

        Returns:
            True if successful, False otherwise
        """
        # Get session
        session = await self.session_manager.get_session(session_id)
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
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            command,
            shell=self.config["computer"]["default_shell"],
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=append_exit_marker,
        )

        if not success:
            adapter = await self._get_adapter_for_session(session_id)
            await adapter.send_message(session_id, f"Failed to execute command: {command}")
            logger.error("Failed to execute command in session %s: %s", session_id[:8], command)
            return False

        # Store exit marker status for polling
        self.exit_marker_appended[session_id] = append_exit_marker

        # Update activity
        await self.session_manager.update_last_activity(session_id)
        await self.session_manager.increment_command_count(session_id)

        # Start polling if exit marker was appended
        if append_exit_marker:
            await self._poll_and_send_output(session_id, session.tmux_session_name)

        logger.info("Executed command in session %s: %s", session_id[:8], command)
        return True

    async def _migrate_session_metadata(self) -> None:
        """Migrate old session metadata to new format.

        Old format: {"topic_id": 12345}
        New format: {"channel_id": "12345"}
        """
        sessions = await self.session_manager.list_sessions()
        migrated = 0

        for session in sessions:
            if not session.adapter_metadata:
                continue

            # Check if migration needed (has topic_id but not channel_id)
            if "topic_id" in session.adapter_metadata and "channel_id" not in session.adapter_metadata:
                # Migrate: rename topic_id to channel_id
                new_metadata = session.adapter_metadata.copy()
                new_metadata["channel_id"] = str(new_metadata.pop("topic_id"))

                # Serialize to JSON for database storage
                await self.session_manager.update_session(session.session_id, adapter_metadata=json.dumps(new_metadata))
                migrated += 1
                logger.debug("Migrated session %s metadata", session.session_id[:8])

        if migrated > 0:
            logger.info("Migrated %d session(s) to new metadata format", migrated)

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting TeleClaude daemon...")

        # Initialize database
        await self.session_manager.initialize()
        logger.info("Database initialized")

        # Migrate old session metadata
        await self._migrate_session_metadata()

        # Start all adapters
        for adapter_name, adapter in self.adapters.items():
            await adapter.start()
            logger.info("%s adapter started", adapter_name.capitalize())

        # Start FastAPI REST API in background task
        import uvicorn

        config = uvicorn.Config(
            self.rest_api.get_asgi_app(),
            host=self.rest_api.bind_address,
            port=self.rest_api.port,
            log_level="info",
            access_log=False,  # Reduce noise
        )
        self.uvicorn_server = uvicorn.Server(config)
        self.api_task = asyncio.create_task(self.uvicorn_server.serve())
        logger.info("REST API started on http://%s:%s", self.rest_api.bind_address, self.rest_api.port)

        # Start periodic cleanup task (runs every hour)
        self.cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("Periodic cleanup task started (72h session lifecycle)")

        logger.info("TeleClaude is running. Press Ctrl+C to stop.")

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
            sessions = await self.session_manager.list_sessions()

            for session in sessions:
                if session.status != "active":
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
                    await self.terminal.kill_session(session.tmux_session_name)

                    # Mark as closed
                    await self.session_manager.update_session(session.session_id, status="closed")

                    logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

        except Exception as e:
            logger.error("Error cleaning up inactive sessions: %s", e)

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

        # Stop all adapters
        for adapter_name, adapter in self.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            await adapter.stop()

        # Stop REST API
        if hasattr(self, "uvicorn_server"):
            self.uvicorn_server.should_exit = True
            await self.api_task

        # Close database
        await self.session_manager.close()

        logger.info("Daemon stopped")

    async def handle_command(self, command: str, args: List[str], context: Dict[str, Any]) -> None:
        """Handle bot commands.

        Args:
            command: Command name (without /)
            args: Command arguments
            context: Platform-specific context
        """
        logger.info("Command received: /%s %s", command, args)

        if command == "new-session":
            await self._create_session(context, args)
        elif command == "list-sessions":
            await self._list_sessions(context)
        elif command == "cancel":
            await self._cancel_command(context)
        elif command == "cancel2x":
            await self._cancel_command(context, double=True)
        elif command == "escape":
            await self._escape_command(context)
        elif command == "escape2x":
            await self._escape_command(context, double=True)
        elif command == "resize":
            await self._resize_session(context, args)
        elif command == "rename":
            await self._rename_session(context, args)
        elif command == "cd":
            await self._cd_session(context, args)
        elif command == "claude":
            await self._claude_session(context)
        elif command == "claude_resume":
            await self._claude_resume_session(context)
        elif command == "exit":
            await self._exit_session(context)

    async def _create_session(self, context: Dict[str, Any], args: List[str]) -> None:
        """Create a new terminal session."""
        # Get adapter_type from context
        adapter_type = context.get("adapter_type")
        if not adapter_type:
            raise ValueError("Context missing adapter_type")

        computer_name = self.config["computer"]["name"]
        working_dir = os.path.expanduser(self.config["computer"]["default_working_dir"])
        shell = self.config["computer"]["default_shell"]
        terminal_size = self.config["terminal"]["default_size"]

        # Generate tmux session name
        session_suffix = str(uuid.uuid4())[:8]
        tmux_name = f"{computer_name.lower()}-session-{session_suffix}"

        # Create topic first with custom title if provided
        if args and len(args) > 0:
            base_title = f"# {computer_name} - {' '.join(args)}"
        else:
            base_title = f"# {computer_name} - New session"

        # Check for duplicate titles and append number if needed
        title = base_title
        existing_sessions = await self.session_manager.list_sessions()
        existing_titles = {s.title for s in existing_sessions if s.status != "closed"}

        if title in existing_titles:
            counter = 2
            while f"{base_title} ({counter})" in existing_titles:
                counter += 1
            title = f"{base_title} ({counter})"

        # Get adapter and create channel
        adapter = self._get_adapter_by_type(adapter_type)
        channel_id = await adapter.create_channel(session_id="temp", title=title)

        # Create session in database
        session = await self.session_manager.create_session(
            computer_name=computer_name,
            tmux_session_name=tmux_name,
            adapter_type=adapter_type,
            title=title,
            adapter_metadata={"channel_id": channel_id},
            terminal_size=terminal_size,
            working_directory=working_dir,
        )

        # Create actual tmux session
        cols, rows = map(int, terminal_size.split("x"))
        success = await self.terminal.create_tmux_session(
            name=tmux_name, shell=shell, working_dir=working_dir, cols=cols, rows=rows
        )

        if success:
            # Send welcome message to topic
            welcome = f"""Session created!

Computer: {computer_name}
Working directory: {working_dir}
Shell: {shell}

You can now send commands to this session.
"""
            adapter = await self._get_adapter_for_session(session.session_id)
            await adapter.send_message(session.session_id, welcome)
            logger.info("Created session: %s", session.session_id)
        else:
            await self.session_manager.delete_session(session.session_id)
            logger.error("Failed to create tmux session")

    async def _list_sessions(self, context: Dict[str, Any]) -> None:
        """List all active sessions."""
        # Get adapter from context
        adapter_type = context.get("adapter_type")
        if not adapter_type:
            logger.error("Cannot send general message - no adapter_type in context")
            return

        adapter = self._get_adapter_by_type(adapter_type)

        sessions = await self.session_manager.list_sessions(status="active")

        if not sessions:
            # Send to General topic
            await adapter.send_general_message(
                text="No active sessions.",
                metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "MarkdownV2"},
            )
            return

        # Build response
        lines = ["**Active Sessions:**\n"]
        for s in sessions:
            lines.append(
                f"• {s.title}\n"
                f"  ID: {s.session_id[:8]}...\n"
                f"  Created: {s.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )

        response = "\n".join(lines)

        # Send to same topic where command was issued
        await adapter.send_general_message(
            text=response, metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "MarkdownV2"}
        )

    async def _cancel_command(self, context: Dict[str, Any], double: bool = False) -> None:
        """Send CTRL+C (SIGINT) to a session.

        Args:
            context: Command context
            double: If True, send CTRL+C twice (for stubborn programs like Claude Code)
        """
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in cancel command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Send SIGINT (CTRL+C) to the tmux session
        success = await self.terminal.send_signal(session.tmux_session_name, "SIGINT")

        if double and success:
            # Wait a moment then send second SIGINT
            await asyncio.sleep(0.2)
            success = await self.terminal.send_signal(session.tmux_session_name, "SIGINT")

        if success:
            logger.info("Sent %s SIGINT to session %s", "double" if double else "single", session_id[:8])
            # Poll for output (the terminal will show the ^C and any output from the interrupted command)
            await self._poll_and_send_output(session_id, session.tmux_session_name)
        else:
            logger.error("Failed to send SIGINT to session %s", session_id[:8])

    async def _escape_command(self, context: Dict[str, Any], double: bool = False) -> None:
        """Send ESCAPE key to a session.

        Args:
            context: Command context
            double: If True, send ESCAPE twice (for Vim, etc.)
        """
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in escape command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Send ESCAPE to the tmux session
        success = await self.terminal.send_escape(session.tmux_session_name)

        if double and success:
            # Wait a moment then send second ESCAPE
            await asyncio.sleep(0.2)
            success = await self.terminal.send_escape(session.tmux_session_name)

        if success:
            logger.info("Sent %s ESCAPE to session %s", "double" if double else "single", session_id[:8])
            # Poll for output (the terminal will show any output from the escape action)
            await self._poll_and_send_output(session_id, session.tmux_session_name)
        else:
            logger.error("Failed to send ESCAPE to session %s", session_id[:8])

    async def _resize_session(self, context: Dict[str, Any], args: List[str]) -> None:
        """Resize terminal session."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in resize command context")
            return

        if not args:
            logger.warning("No size argument provided to resize command")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Size presets
        size_presets = {
            "small": "80x24",
            "medium": "120x40",
            "large": "160x60",
            "wide": "200x80",
        }

        # Get size (either preset name or direct WxH format)
        size_str = args[0].lower()
        size_str = size_presets.get(size_str, size_str)

        # Parse size
        try:
            cols, rows = map(int, size_str.split("x"))
        except ValueError:
            logger.error("Invalid size format: %s", size_str)
            adapter = await self._get_adapter_for_session(session_id)
            await adapter.send_message(session_id, f"Invalid size format: {size_str}")
            return

        # Resize the tmux session
        success = await self.terminal.resize_session(session.tmux_session_name, cols, rows)

        # Get adapter for sending messages
        adapter = await self._get_adapter_for_session(session_id)

        if success:
            # Update session in database
            await self.session_manager.update_session(session_id, terminal_size=size_str)
            logger.info("Resized session %s to %s", session_id[:8], size_str)
            await adapter.send_message(session_id, f"Terminal resized to {size_str} ({cols}x{rows})")
        else:
            logger.error("Failed to resize session %s", session_id[:8])
            await adapter.send_message(session_id, "Failed to resize terminal")

    async def _rename_session(self, context: Dict[str, Any], args: List[str]) -> None:
        """Rename session."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in rename command context")
            return

        if not args:
            logger.warning("No name argument provided to rename command")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Build new title with computer name prefix
        computer_name = self.config["computer"]["name"]
        new_title = f"[{computer_name}] {' '.join(args)}"

        # Update in database
        await self.session_manager.update_session(session_id, title=new_title)

        # Update channel title (topic_id for backward compat, channel_id is new standard)
        channel_id = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")
        if channel_id:
            adapter = await self._get_adapter_for_session(session_id)
            success = await adapter.update_channel_title(str(channel_id), new_title)
            if success:
                logger.info("Renamed session %s to '%s'", session_id[:8], new_title)
                await adapter.send_message(session_id, f"Session renamed to: {new_title}")
            else:
                logger.error("Failed to update channel title for session %s", session_id[:8])
                await adapter.send_message(session_id, "Failed to update channel title")
        else:
            logger.error("No channel_id for session %s", session_id[:8])

    async def _cd_session(self, context: Dict[str, Any], args: List[str]) -> None:
        """Change directory in session or list trusted directories."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in cd command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Get adapter for sending messages
        adapter = await self._get_adapter_for_session(session_id)

        # If no args, list trusted directories
        if not args:
            # Always prepend TC WORKDIR to the list
            trusted_dirs = ["TC WORKDIR"] + self.config.get("computer", {}).get("trustedDirs", [])

            lines = ["**Trusted Directories:**\n"]
            for idx, dir_path in enumerate(trusted_dirs, 1):
                lines.append(f"{idx}. {dir_path}")

            response = "\n".join(lines)
            await adapter.send_message(session_id, response)
            return

        # Change to specified directory
        target_dir = " ".join(args)

        # Handle TC WORKDIR special case
        if target_dir == "TC WORKDIR":
            target_dir = os.path.expanduser(self.config["computer"]["default_working_dir"])
        cd_command = f"cd {shlex.quote(target_dir)}"

        # Execute command and start polling
        await self._execute_terminal_command(session_id, cd_command)

    async def _exit_session(self, context: Dict[str, Any]) -> None:
        """Exit session - kill tmux session and delete topic."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in exit command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Get adapter
        adapter = await self._get_adapter_for_session(session_id)

        # Kill tmux session
        success = await self.terminal.kill_session(session.tmux_session_name)
        if success:
            logger.info("Killed tmux session %s", session.tmux_session_name)
        else:
            logger.warning("Failed to kill tmux session %s", session.tmux_session_name)

        # Delete from database
        await self.session_manager.delete_session(session_id)
        logger.info("Deleted session %s from database", session_id[:8])

        # Delete persistent output file
        try:
            output_file = self._get_output_file(session_id)
            if output_file.exists():
                output_file.unlink()
                logger.debug("Deleted output file for closed session %s", session_id[:8])
        except Exception as e:
            logger.warning("Failed to delete output file: %s", e)

        # Delete channel/topic
        channel_id = session.adapter_metadata.get("channel_id")
        if channel_id:
            await adapter.delete_channel(str(channel_id))
            logger.info("Deleted channel %s", channel_id)

    async def _claude_session(self, context: Dict[str, Any]) -> None:
        """Start Claude Code in session."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in claude command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Execute command and start polling
        await self._execute_terminal_command(session_id, "claude --dangerously-skip-permissions")

    async def _claude_resume_session(self, context: Dict[str, Any]) -> None:
        """Resume last Claude Code session (claude --continue)."""
        session_id = context.get("session_id")
        if not session_id:
            logger.warning("No session_id in claude_resume command context")
            return

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Execute command and start polling
        await self._execute_terminal_command(session_id, "claude --dangerously-skip-permissions --continue")

    async def handle_message(self, session_id: str, text: str, context: Dict[str, Any]) -> None:
        """Handle incoming text messages (commands for terminal).

        Args:
            session_id: Session ID
            text: Message text (command to execute)
            context: Platform-specific context
        """
        logger.debug("Message for session %s: %s...", session_id[:8], text[:50])

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Delete idle notification if one exists (user is interacting now)
        if session_id in self.idle_notifications:
            adapter = await self._get_adapter_for_session(session_id)
            notification_msg_id = self.idle_notifications.pop(session_id)
            await adapter.delete_message(session_id, notification_msg_id)
            logger.debug(
                "Deleted idle notification %s for session %s (user sent command)", notification_msg_id, session_id[:8]
            )

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
        is_process_running = session_id in self.active_polling_sessions

        # Send command to terminal (will create fresh session if needed)
        # Only append exit marker if starting a NEW command, not sending input to running process
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            text,
            shell=self.config["computer"]["default_shell"],
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=not is_process_running,
        )

        adapter = await self._get_adapter_for_session(session_id)

        if not success:
            logger.error("Failed to send command to session %s", session_id[:8])
            await adapter.send_message(session_id, "Failed to send command to terminal")
            return

        # Track whether exit marker was appended
        self.exit_marker_appended[session_id] = not is_process_running

        # Update activity
        await self.session_manager.update_last_activity(session_id)
        await self.session_manager.increment_command_count(session_id)

        # Delete user message if polling is active (message gets absorbed as input)
        if is_process_running:
            message_id = context.get("message_id")
            if message_id:
                await adapter.delete_message(session_id, str(message_id))
                logger.debug("Deleted user message %s for session %s (absorbed as input)", message_id, session_id[:8])
            # Don't start new poll - existing poll loop will capture the output
            logger.debug(
                "Input sent to running process in session %s, existing poll will capture output", session_id[:8]
            )
        else:
            # Start new poll loop for this command
            await self._poll_and_send_output(session_id, session.tmux_session_name)

    async def handle_voice(self, session_id: str, audio_path: str, context: Dict[str, Any]) -> None:
        """Handle incoming voice messages.

        Args:
            session_id: Session ID
            audio_path: Path to downloaded audio file
            context: Platform-specific context (includes duration, user_id, etc.)
        """
        logger.info("=== DAEMON HANDLE_VOICE CALLED ===")
        logger.info("Session ID: %s", session_id[:8])
        logger.info("Audio path: %s", audio_path)
        logger.info("Context: %s", context)
        logger.info("Voice message for session %s, duration: %ss", session_id[:8], context.get("duration"))

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Get adapter for sending messages
        adapter = await self._get_adapter_for_session(session_id)

        # Check if a process is currently running (polling active)
        is_process_running = session_id in self.active_polling_sessions

        # Reject voice messages if no active process to send them to
        if not is_process_running:
            await adapter.send_message(session_id, "🎤 Voice input requires an active process (e.g., claude, vim)")
            # Clean up temp file
            try:
                Path(audio_path).unlink()
                logger.debug("Cleaned up voice file (rejected - no active process): %s", audio_path)
            except Exception as e:
                logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
            return

        # Voice message accepted - transcribe and send to active process
        output_file = self._get_output_file(session_id)

        # Check if output message exists (polling may have just started)
        current_message_id = await self.session_manager.get_output_message_id(session_id)
        if current_message_id is None:
            logger.warning("No output message yet for session %s, polling may have just started", session_id[:8])
            # Send rejection message
            await adapter.send_message(
                session_id, "⚠️ Voice input unavailable - output message not ready yet (try again in 1-2 seconds)"
            )
            # Clean up temp file
            try:
                Path(audio_path).unlink()
                logger.debug("Cleaned up voice file (no message_id yet): %s", audio_path)
            except Exception as e:
                logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
            return

        # Send transcribing status (append to existing output)
        msg_id = await self.message_manager.send_status_message(
            session_id,
            adapter,
            "🎤 Transcribing...",
            append_to_existing=True,
            output_file_path=str(output_file),
        )
        if msg_id is None:
            logger.info("Topic deleted for session %s, skipping transcription", session_id[:8])
            # Clean up temp file before returning
            try:
                Path(audio_path).unlink()
                logger.debug("Cleaned up voice file: %s", audio_path)
            except Exception as e:
                logger.warning("Failed to clean up voice file %s: %s", audio_path, e)
            return

        # Transcribe audio using Whisper
        transcribed_text = await self.voice_handler.transcribe_with_retry(audio_path)

        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file: %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)

        if not transcribed_text:
            # Append error to existing message
            await self.message_manager.send_status_message(
                session_id,
                adapter,
                "❌ Transcription failed. Please try again.",
                append_to_existing=True,
                output_file_path=str(output_file),
            )
            return

        # Send transcribed text as input to the running process
        logger.debug("Sending transcribed text as input to session %s: %s", session_id[:8], transcribed_text)
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            transcribed_text,
            append_exit_marker=False,  # Never append exit marker - we're sending input to a running process
        )

        if not success:
            logger.error("Failed to send transcribed input to session %s", session_id[:8])
            await adapter.send_message(session_id, "❌ Failed to send input to terminal")
            return

        # Update activity
        await self.session_manager.update_last_activity(session_id)

        # Voice input sent to running process - existing poll will capture output
        logger.debug(
            "Voice input sent to running process in session %s, existing poll will capture output", session_id[:8]
        )

    async def handle_topic_closed(self, session_id: str, context: Dict[str, Any]) -> None:
        """Handle topic/channel closure event.

        Args:
            session_id: Session ID
            context: Platform-specific context (includes topic_id, user_id, etc.)
        """
        logger.info("Topic closed for session %s, closing session and tmux", session_id[:8])

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found during topic closure", session_id)
            return

        # Kill the tmux session
        tmux_session_name = session.tmux_session_name
        logger.info("Killing tmux session: %s", tmux_session_name)
        success = await self.terminal.kill_session(tmux_session_name)
        if not success:
            logger.warning("Failed to kill tmux session %s", tmux_session_name)

        # Mark session as closed in database
        await self.session_manager.update_session(session_id, status="closed")
        logger.info("Session %s marked as closed", session_id[:8])

    async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None:
        """Poll terminal output and send to chat adapter.

        Pure orchestration - consumes events from poller, delegates to message manager.
        SINGLE RESPONSIBILITY: Owns the polling lifecycle for a session.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
        """
        # GUARD: Prevent duplicate polling (check and add atomically before any await)
        if session_id in self.active_polling_sessions:
            logger.warning(
                "Polling already active for session %s, ignoring duplicate request",
                session_id[:8],
            )
            return

        # Mark as active BEFORE any await (prevents race conditions)
        self.active_polling_sessions.add(session_id)

        # Get adapter for this session
        adapter = await self._get_adapter_for_session(session_id)

        # Get output file and exit marker status
        output_file = self._get_output_file(session_id)
        # Check in-memory first (for current polling), fallback to DB (for resumed polling after restart)
        has_exit_marker = self.exit_marker_appended.get(
            session_id, bool(await self.session_manager.get_output_message_id(session_id))
        )

        try:
            # Consume events from pure poller
            async for event in self.output_poller.poll(session_id, tmux_session_name, output_file, has_exit_marker):
                if isinstance(event, OutputChanged):
                    # Output changed - send update
                    await self.message_manager.send_output_update(
                        event.session_id,
                        adapter,
                        event.output,
                        event.started_at,
                        event.last_changed_at,
                        max_message_length=3800,
                    )

                    # Delete idle notification if one exists (output resumed)
                    notification_id = await self.session_manager.get_idle_notification_message_id(event.session_id)
                    if notification_id:
                        await adapter.delete_message(event.session_id, notification_id)
                        await self.session_manager.set_idle_notification_message_id(event.session_id, None)
                        logger.debug(
                            "Deleted idle notification %s for session %s", notification_id, event.session_id[:8]
                        )

                elif isinstance(event, IdleDetected):
                    # Idle detected - send notification
                    notification = (
                        f"⏸️ No output for {event.idle_seconds} seconds - "
                        "process may be waiting or hung up, try cancel"
                    )
                    notification_id = await adapter.send_message(event.session_id, notification)
                    if notification_id:
                        # Persist to DB (survives daemon restart)
                        await self.session_manager.set_idle_notification_message_id(event.session_id, notification_id)
                        logger.debug(
                            "Stored idle notification %s for session %s", notification_id, event.session_id[:8]
                        )

                elif isinstance(event, ProcessExited):
                    # Process exited
                    if event.exit_code is not None:
                        # Exit with code - send final message (edits existing message)
                        await self.message_manager.send_output_update(
                            event.session_id,
                            adapter,
                            event.final_output,
                            event.started_at,  # Use actual start time from poller
                            time.time(),
                            max_message_length=3800,
                            is_final=True,
                            exit_code=event.exit_code,
                        )
                        logger.info(
                            "Polling stopped for %s (exit code: %d), output file kept for downloads",
                            event.session_id[:8],
                            event.exit_code,
                        )
                    else:
                        # Session died - send exit message
                        await self.message_manager.send_exit_message(
                            event.session_id, adapter, event.final_output, "✅ Process exited"
                        )
                        # Delete output file on session death
                        try:
                            if output_file.exists():
                                output_file.unlink()
                                logger.debug("Deleted output file for exited session %s", event.session_id[:8])
                        except Exception as e:
                            logger.warning("Failed to delete output file: %s", e)

                    # Clear output_message_id so next input starts fresh
                    await self.session_manager.set_output_message_id(event.session_id, None)

        finally:
            # Cleanup
            self.active_polling_sessions.discard(session_id)
            self.exit_marker_appended.pop(session_id, None)
            await self.session_manager.set_idle_notification_message_id(session_id, None)
            logger.debug("Polling ended for session %s", session_id[:8])


async def main() -> None:
    """Main entry point."""
    # Find config files
    base_dir = Path(__file__).parent.parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    # Load environment variables first (for config variable expansion)
    load_dotenv(env_path)

    # Load config to get logging path (config.yml is the source of truth)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Expand environment variables in config
    config = expand_env_vars(config)

    # Setup logging using config.yml (source of truth)
    log_file = os.path.expanduser(config.get("logging", {}).get("file", str(base_dir / "logs" / "teleclaude.log")))
    log_level = config.get("logging", {}).get("level", "INFO")
    setup_logging(level=log_level, log_file=log_file)

    # Create daemon
    daemon = TeleClaudeDaemon(str(config_path), str(env_path))

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum: int, frame: Any) -> None:
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
