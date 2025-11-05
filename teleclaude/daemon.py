"""TeleClaude main daemon."""

import asyncio
import atexit
import fcntl
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

import yaml
from dotenv import load_dotenv

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import init_config
from teleclaude.core import terminal_bridge  # Imported for test mocking
from teleclaude.core import (
    command_handlers,
    event_handlers,
    message_handler,
    polling_coordinator,
    session_lifecycle,
    terminal_executor,
    ux_state,
    voice_message_handler,
)
from teleclaude.core.computer_registry import ComputerRegistry
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.voice_handler import init_voice_handler
from teleclaude.logging_config import setup_logging
from teleclaude.mcp_server import TeleClaudeMCPServer
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

        # Initialize global config for all modules
        init_config(self.config)

        # PID file for locking - use project root
        project_root = Path(__file__).parent.parent
        self.pid_file = project_root / "teleclaude.pid"
        self.pid_file_handle: Optional[TextIO] = None  # Will hold the locked file handle

        # Initialize core components
        db_path = os.path.expanduser(self.config["database"]["path"])
        self.session_manager = SessionManager(db_path)
        # Note: terminal_bridge and output_message_manager are now functional modules (no instantiation)
        self.output_poller = OutputPoller(self.config, self.session_manager)

        # Adapter registry - stores all active adapters
        self.adapters: Dict[str, BaseAdapter] = {}

        # Primary adapter (for commands in "General" topic) - first adapter wins
        self.primary_adapter: Optional[BaseAdapter] = None

        # Output file directory (persistent files for download button)
        self.output_dir = Path("session_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize REST API
        api_port = int(os.getenv("PORT", self.config.get("rest_api", {}).get("port", 6666)))
        self.rest_api = TeleClaudeAPI(
            session_manager=self.session_manager,
            bind_address="127.0.0.1",
            port=api_port,
        )

        # Load adapters from config
        self._load_adapters()

        # For backward compatibility (temporary - will be removed after full migration)
        # This allows existing code to use self.telegram during migration
        if "telegram" in self.adapters:
            self.telegram = self.adapters["telegram"]

        # Initialize computer registry (if MCP enabled and telegram adapter exists)
        self.computer_registry: Optional[ComputerRegistry] = None
        self.mcp_server: Optional[TeleClaudeMCPServer] = None

        if self.config.get("mcp", {}).get("enabled", False) and "telegram" in self.adapters:
            computer_name = self.config["computer"]["name"]
            bot_username = self.config["computer"].get("bot_username", f"teleclaude_{computer_name}_bot")

            self.computer_registry = ComputerRegistry(
                telegram_adapter=self.adapters["telegram"],
                computer_name=computer_name,
                bot_username=bot_username,
                config=self.config,
                session_manager=self.session_manager,
            )

            self.mcp_server = TeleClaudeMCPServer(
                config=self.config,
                telegram_adapter=self.adapters["telegram"],
                terminal_bridge=terminal_bridge,
                session_manager=self.session_manager,
                computer_registry=self.computer_registry,
            )

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
                "trusted_bots": self.config.get("telegram", {}).get("trusted_bots", []),
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
        message_id: str = None,
    ) -> bool:
        """Execute command in terminal and start polling if needed.

        Wrapper around terminal_executor.execute_terminal_command that provides dependencies.

        Args:
            session_id: Session ID
            command: Command to execute
            append_exit_marker: Whether to append exit marker (default: True)
            message_id: Message ID to cleanup (optional)

        Returns:
            True if successful, False otherwise
        """
        return await terminal_executor.execute_terminal_command(
            session_id=session_id,
            command=command,
            session_manager=self.session_manager,
            config=self.config,
            get_adapter_for_session=self._get_adapter_for_session,
            start_polling=self._poll_and_send_output,
            append_exit_marker=append_exit_marker,
            message_id=message_id,
        )

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting TeleClaude daemon...")

        # Initialize database
        await self.session_manager.initialize()
        logger.info("Database initialized")

        # Initialize voice handler
        init_voice_handler()
        logger.info("Voice handler initialized")

        # Migrate old session metadata
        await session_lifecycle.migrate_session_metadata(self.session_manager)

        # State is now DB-backed via session_manager - no need to load from database

        # Start all adapters
        for adapter_name, adapter in self.adapters.items():
            await adapter.start()
            logger.info("%s adapter started", adapter_name.capitalize())

        # Start computer registry (if enabled)
        if self.computer_registry:
            await self.computer_registry.start()
            logger.info("Computer registry started")

        # Start MCP server in background task (if enabled)
        if self.mcp_server:
            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            logger.info("MCP server starting in background")

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
        self.cleanup_task = asyncio.create_task(session_lifecycle.periodic_cleanup(self.session_manager, self.config))
        logger.info("Periodic cleanup task started (72h session lifecycle)")

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
            await command_handlers.handle_create_session(context, args, self.session_manager, self._get_adapter_by_type)
        elif command == "list-sessions":
            await command_handlers.handle_list_sessions(context, self.session_manager, self._get_adapter_by_type)
        elif command == "cancel":
            await command_handlers.handle_cancel_command(
                context, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output
            )
        elif command == "cancel2x":
            await command_handlers.handle_cancel_command(
                context, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output, double=True
            )
        elif command == "escape":
            await command_handlers.handle_escape_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output
            )
        elif command == "escape2x":
            await command_handlers.handle_escape_command(
                context,
                args,
                self.session_manager,
                self._get_adapter_for_session,
                self._poll_and_send_output,
                double=True,
            )
        elif command == "ctrl":
            await command_handlers.handle_ctrl_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output
            )
        elif command == "tab":
            await command_handlers.handle_tab_command(
                context, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output
            )
        elif command == "shift-tab":
            await command_handlers.handle_shift_tab_command(
                context, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output
            )
        elif command == "key-up":
            await command_handlers.handle_arrow_key_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output, "up"
            )
        elif command == "key-down":
            await command_handlers.handle_arrow_key_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output, "down"
            )
        elif command == "key-left":
            await command_handlers.handle_arrow_key_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output, "left"
            )
        elif command == "key-right":
            await command_handlers.handle_arrow_key_command(
                context, args, self.session_manager, self._get_adapter_for_session, self._poll_and_send_output, "right"
            )
        elif command == "resize":
            await command_handlers.handle_resize_session(
                context, args, self.session_manager, self._get_adapter_for_session
            )
        elif command == "rename":
            await command_handlers.handle_rename_session(
                context, args, self.session_manager, self._get_adapter_for_session
            )
        elif command == "cd":
            await command_handlers.handle_cd_session(
                context, args, self.session_manager, self._get_adapter_for_session, self._execute_terminal_command
            )
        elif command == "claude":
            await command_handlers.handle_claude_session(context, self.session_manager, self._execute_terminal_command)
        elif command == "claude_resume":
            await command_handlers.handle_claude_resume_session(
                context, self.session_manager, self._execute_terminal_command
            )
        elif command == "exit":
            await command_handlers.handle_exit_session(
                context, self.session_manager, self._get_adapter_for_session, self._get_output_file
            )

    async def handle_message(self, session_id: str, text: str, context: Dict[str, Any]) -> None:
        """Wrapper around message_handler.handle_message."""
        await message_handler.handle_message(
            session_id=session_id,
            text=text,
            context=context,
            session_manager=self.session_manager,
            config=self.config,
            get_adapter_for_session=self._get_adapter_for_session,
            start_polling=self._poll_and_send_output,
        )

    async def handle_voice(self, session_id: str, audio_path: str, context: Dict[str, Any]) -> None:
        """Wrapper around voice_message_handler.handle_voice."""
        await voice_message_handler.handle_voice(
            session_id=session_id,
            audio_path=audio_path,
            context=context,
            session_manager=self.session_manager,
            get_adapter_for_session=self._get_adapter_for_session,
            get_output_file=self._get_output_file,
        )

    async def handle_topic_closed(self, session_id: str, context: Dict[str, Any]) -> None:
        """Handle topic/channel closure event.

        Wrapper around event_handlers.handle_topic_closed that provides dependencies.

        Args:
            session_id: Session ID
            context: Platform-specific context (includes topic_id, user_id, etc.)
        """
        await event_handlers.handle_topic_closed(
            session_id=session_id,
            context=context,
            session_manager=self.session_manager,
        )

    async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None:
        """Wrapper around polling_coordinator.poll_and_send_output."""
        await polling_coordinator.poll_and_send_output(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            session_manager=self.session_manager,
            output_poller=self.output_poller,
            get_adapter_for_session=self._get_adapter_for_session,
            get_output_file=self._get_output_file,
        )


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
    log_file = "/var/log/teleclaude.log"
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
