"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import json
import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

import yaml
from dotenv import load_dotenv

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge
from teleclaude.core.voice_handler import VoiceHandler
from teleclaude.logging_config import setup_logging
from teleclaude.rest_api import TeleClaudeAPI

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
        self.config = self._expand_env_vars(self.config)

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: Optional[TextIO] = None  # Will hold the locked file handle

        # Initialize core components
        db_path = os.path.expanduser(self.config["database"]["path"])
        self.session_manager = SessionManager(db_path)
        self.terminal = TerminalBridge()
        self.voice_handler = VoiceHandler()

        # Adapter registry - stores all active adapters
        self.adapters: Dict[str, BaseAdapter] = {}

        # Primary adapter (for commands in "General" topic) - first adapter wins
        self.primary_adapter: Optional[BaseAdapter] = None

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

    def _expand_env_vars(self, config: Any) -> Any:
        """Recursively expand environment variables in config."""
        if isinstance(config, dict):
            return {k: self._expand_env_vars(v) for k, v in config.items()}
        if isinstance(config, list):
            return [self._expand_env_vars(item) for item in config]
        if isinstance(config, str):
            # Replace ${VAR} with environment variable value
            def replace_env_var(match: re.Match[str]) -> str:
                env_var = match.group(1)
                return os.getenv(env_var, match.group(0))

            return re.sub(r"\$\{([^}]+)\}", replace_env_var, config)
        else:
            return config

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

            self.adapters["telegram"] = TelegramAdapter(telegram_config, self.session_manager)

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

        logger.info("TeleClaude is running. Press Ctrl+C to stop.")

    async def stop(self) -> None:
        """Stop the daemon."""
        logger.info("Stopping TeleClaude daemon...")

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
            title = f"[{computer_name}] {' '.join(args)}"
        else:
            title = f"[{computer_name}] New session"

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
                metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "Markdown"},
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
            text=response, metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "Markdown"}
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

        # Send command to terminal
        success = await self.terminal.send_keys(session.tmux_session_name, cd_command)

        if success:
            # Update activity
            await self.session_manager.update_last_activity(session_id)
            await self.session_manager.increment_command_count(session_id)

            # Poll for output
            await self._poll_and_send_output(session_id, session.tmux_session_name)
            logger.info("Changed directory in session %s to: %s", session_id[:8], target_dir)
        else:
            logger.error("Failed to send cd command to session %s", session_id[:8])
            await adapter.send_message(session_id, f"Failed to change directory to: {target_dir}")

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

        # Parse terminal size
        cols, rows = map(int, session.terminal_size.split("x"))

        # Get shell from config
        shell = self.config["computer"]["default_shell"]

        # Send Claude Code command (will create fresh session if needed)
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            "claude --dangerously-skip-permissions",
            shell=shell,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if success:
            # Update activity
            await self.session_manager.update_last_activity(session_id)
            await self.session_manager.increment_command_count(session_id)

            # Poll for output
            await self._poll_and_send_output(session_id, session.tmux_session_name)
            logger.info("Started Claude Code in session %s", session_id[:8])
        else:
            logger.error("Failed to send claude command to session %s", session_id[:8])
            adapter = await self._get_adapter_for_session(session_id)
            await adapter.send_message(session_id, "Failed to start Claude Code")

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

        # Parse terminal size for auto-recovery
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Send "claude --dangerously-skip-permissions --continue" command (will create fresh session if needed)
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            "claude --dangerously-skip-permissions --continue",
            shell=self.config["computer"]["default_shell"],
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if success:
            # Update activity
            await self.session_manager.update_last_activity(session_id)
            await self.session_manager.increment_command_count(session_id)

            # Poll for output
            await self._poll_and_send_output(session_id, session.tmux_session_name)
            logger.info("Resumed Claude Code session in %s", session_id[:8])
        else:
            logger.error("Failed to send claude --continue command to session %s", session_id[:8])
            adapter = await self._get_adapter_for_session(session_id)
            await adapter.send_message(session_id, "Failed to resume Claude Code session")

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

        # Parse terminal size (e.g., "80x24" -> cols=80, rows=24)
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Send command to terminal (will create fresh session if needed)
        success = await self.terminal.send_keys(
            session.tmux_session_name,
            text,
            shell=self.config["computer"]["default_shell"],
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
        )

        if success:
            # Update activity
            await self.session_manager.update_last_activity(session_id)
            await self.session_manager.increment_command_count(session_id)

            # Poll for output with hybrid mode (edit message as output grows)
            await self._poll_and_send_output(session_id, session.tmux_session_name)
        else:
            logger.error("Failed to send command to session %s", session_id[:8])
            adapter = await self._get_adapter_for_session(session_id)
            await adapter.send_message(session_id, "Failed to send command to terminal")

    async def handle_voice(self, session_id: str, audio_path: str, context: Dict[str, Any]) -> None:
        """Handle incoming voice messages.

        Args:
            session_id: Session ID
            audio_path: Path to downloaded audio file
            context: Platform-specific context (includes duration, user_id, etc.)
        """
        logger.info("Voice message for session %s, duration: %ss", session_id[:8], context.get("duration"))

        # Get session
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("Session %s not found", session_id)
            return

        # Get adapter for sending messages
        adapter = await self._get_adapter_for_session(session_id)

        # Send transcribing message
        await adapter.send_message(session_id, "🎤 Transcribing...")

        # Transcribe audio using Whisper
        transcribed_text = await self.voice_handler.transcribe_with_retry(audio_path)

        # Clean up temp file
        try:
            Path(audio_path).unlink()
            logger.debug("Cleaned up voice file: %s", audio_path)
        except Exception as e:
            logger.warning("Failed to clean up voice file %s: %s", audio_path, e)

        if not transcribed_text:
            await adapter.send_message(session_id, "❌ Transcription failed. Please try again.")
            return

        # Show transcription to user
        await adapter.send_message(session_id, f"🎤 Transcribed: {transcribed_text}")

        # Send transcribed command to terminal
        success = await self.terminal.send_keys(session.tmux_session_name, transcribed_text)

        if success:
            # Update activity
            await self.session_manager.update_last_activity(session_id)
            await self.session_manager.increment_command_count(session_id)

            # Poll for output
            await self._poll_and_send_output(session_id, session.tmux_session_name)
        else:
            logger.error("Failed to send transcribed command to session %s", session_id[:8])
            await adapter.send_message(session_id, "❌ Failed to send command to terminal")

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
        """Poll terminal output and update single message in-place.

        Maintains full output buffer in a file, but only shows last N chars in messages.
        This allows unlimited output while keeping message size manageable.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
        """
        max_message_length = 3800  # Message limit (leave buffer for formatting)
        max_polls = 600  # Maximum 600 polls (10 minutes with 1s interval)
        poll_interval = 1.0  # Poll every 1 second

        # Get adapter for sending messages
        adapter = await self._get_adapter_for_session(session_id)

        # Create output buffer file for this session
        output_dir = Path("logs/session_output")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{session_id[:8]}.txt"

        current_message_id = None  # Track message being edited
        full_buffer = ""  # Complete output buffer (grows indefinitely)
        last_captured_length = 0  # Track how much we've already captured
        consecutive_identical = 0  # Count how many times output was identical

        for _ in range(max_polls):
            # Wait before capturing
            await asyncio.sleep(poll_interval)

            # Capture current output from terminal
            current_output = await self.terminal.capture_pane(tmux_session_name)

            if not current_output.strip():
                # No output yet, continue polling
                continue

            # Check if output changed
            if len(current_output) == last_captured_length:
                consecutive_identical += 1

                # Only stop if:
                # 1. Output hasn't changed for 30 seconds (process likely finished)
                # 2. AND output ends with a shell prompt (indicating command completion)
                if consecutive_identical >= 30:
                    # Check if output ends with typical shell prompt patterns
                    lines = current_output.strip().split("\n")
                    last_line = lines[-1] if lines else ""

                    # Common prompt patterns: ends with $, >, %, #, or "❯"
                    has_prompt = any(last_line.rstrip().endswith(c) for c in ["$", ">", "%", "#", "❯"])

                    if has_prompt:
                        logger.debug("Process finished for %s, stopping poll", session_id[:8])
                        break

                # Continue polling even if no new output (process might still be running)
                continue

            # We have new output, reset counter
            consecutive_identical = 0
            last_captured_length = len(current_output)

            # Update full buffer (this grows indefinitely)
            full_buffer = current_output

            # Save full buffer to file for persistence
            try:
                output_file.write_text(full_buffer, encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to save output buffer: %s", e)

            # Prepare display output (sliding window of last N chars)
            display_output = full_buffer
            output_url = None

            if len(full_buffer) > max_message_length:
                # Generate URL to full output (will be served by REST API)
                port = self.rest_api.port
                output_url = f"http://localhost:{port}/api/v1/sessions/{session_id}/output"

                # Show last N chars with link to full output
                header = f"📄 Output too large ({len(full_buffer)} chars)\n"
                header += f"🔗 Full output: {output_url}\n"
                header += f"\n[...showing last {max_message_length - 200} chars...]\n\n"

                display_output = header + full_buffer[-(max_message_length - 200) :]

            if current_message_id:
                # Edit existing message
                success = await adapter.edit_message(session_id, current_message_id, display_output)
                if success:
                    logger.debug(
                        "Edited message for %s, buffer: %s, shown: %s",
                        session_id[:8],
                        len(full_buffer),
                        len(display_output),
                    )
                else:
                    # Edit failed (message too old or deleted), send new message
                    sent_msg_id = await adapter.send_message(session_id, display_output)
                    if sent_msg_id:
                        current_message_id = sent_msg_id
                        logger.debug("Edit failed, sent new message for %s", session_id[:8])
            else:
                # Send first message
                sent_msg_id = await adapter.send_message(session_id, display_output)
                if sent_msg_id:
                    current_message_id = sent_msg_id
                    logger.debug("Sent initial message for %s, msg_id: %s", session_id[:8], current_message_id)


async def main() -> None:
    """Main entry point."""
    # Find config files
    base_dir = Path(__file__).parent.parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    # Load environment to get log file path
    load_dotenv(env_path)

    # Setup logging
    log_file = os.path.expanduser(os.getenv("LOG_FILE", str(base_dir / "logs" / "teleclaude.log")))
    setup_logging(log_file=log_file)

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
