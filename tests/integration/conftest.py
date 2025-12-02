"""Shared fixtures for integration tests."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="function")
async def daemon_with_mocked_telegram(monkeypatch, tmp_path):
    """Create daemon with mocked Telegram adapter and cleanup all resources.

    Function-scoped fixture ensures each test gets isolated database for parallel execution.
    """
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    # CRITICAL: Set temp database path BEFORE importing teleclaude modules
    # tmp_path is function-scoped, so each test gets unique database automatically
    temp_db_path = str(tmp_path / "test_teleclaude.db")
    monkeypatch.setenv("TELECLAUDE_DB_PATH", temp_db_path)

    # NOW import teleclaude modules (after env var is set)
    from teleclaude import config as config_module
    from teleclaude.core import db as db_module
    from teleclaude.core import terminal_bridge
    from teleclaude.core.db import Db
    from teleclaude.daemon import TeleClaudeDaemon

    # CRITICAL: Mock config exhaustively - ALL sections (no sensitive data)
    class MockDatabase:
        def path(self):
            return str(tmp_path / "test_teleclaude.db")

    class MockComputer:
        name = "TestComputer"
        default_working_dir = "/tmp"
        default_shell = "/bin/sh"
        user = "testuser"
        role = "test"
        host = "test.local"
        timezone = "UTC"
        is_master = False
        trusted_dirs = []

        def get_all_trusted_dirs(self):
            """Return empty list for tests."""
            return []

    class MockPolling:
        idle_notification_seconds = 300

    class MockMCP:
        enabled = False
        socket_path = "/tmp/test.sock"

    class MockRedis:
        enabled = True  # Enable Redis for E2E tests
        url = "redis://localhost:6379"
        password = None
        max_connections = 10
        socket_timeout = 5
        message_stream_maxlen = 1000
        output_stream_maxlen = 1000
        output_stream_ttl = 300

    class MockTelegram:
        is_master = False
        trusted_bots = []

    test_config = type(
        "Config",
        (),
        {
            "database": MockDatabase(),
            "computer": MockComputer(),
            "polling": MockPolling(),
            "mcp": MockMCP(),
            "redis": MockRedis(),
            "telegram": MockTelegram(),
        },
    )()

    monkeypatch.setattr(config_module, "config", test_config)

    # CRITICAL: Reinitialize db singleton with test database path
    # This ensures each test gets isolated database even in parallel execution
    db_module.db = Db(temp_db_path)
    await db_module.db.initialize()

    # CRITICAL: Patch db and config singletons in ALL modules that imported them at module load time
    # Without this, modules keep reference to old instances
    modules_to_patch = [
        "teleclaude.adapters.base_adapter",
        "teleclaude.adapters.telegram_adapter",
        "teleclaude.core.adapter_client",
        "teleclaude.adapters.redis_adapter",
        "teleclaude.daemon",
        "teleclaude.mcp_server",
        "teleclaude.core.polling_coordinator",
        "teleclaude.core.command_handlers",
        "teleclaude.core.session_cleanup",
        "teleclaude.adapters.ui_adapter",
        "teleclaude.core.file_handler",
        "teleclaude.core.session_utils",
        "teleclaude.core.voice_message_handler",
        "teleclaude.core.computer_registry",
    ]

    for module_name in modules_to_patch:
        monkeypatch.setattr(f"{module_name}.db", db_module.db)

    # Patch config only in modules that actually import it
    config_modules = [
        "teleclaude.core.adapter_client",
        "teleclaude.core.command_handlers",
        "teleclaude.core.db",
        "teleclaude.core.output_poller",
        "teleclaude.adapters.redis_adapter",
        "teleclaude.adapters.telegram_adapter",
        "teleclaude.adapters.ui_adapter",
        "teleclaude.daemon",
        "teleclaude.mcp_server",
    ]

    for module_name in config_modules:
        monkeypatch.setattr(f"{module_name}.config", test_config)

    # Create daemon (config is loaded automatically from config.yml)
    daemon = TeleClaudeDaemon(str(base_dir / ".env"))

    # CRITICAL: Mock Redis connection for E2E tests (prevent real network calls)
    # Create a mock Redis client that simulates async Redis interface
    class MockRedisClient:
        """Mock Redis client for E2E testing - simulates streams and pub/sub."""

        def __init__(self):
            self.streams = {}  # {stream_name: [(msg_id, data)]}
            self.data = {}  # {key: value}

        async def xadd(self, stream_name, fields, maxlen=None, id="*"):
            """Add message to stream."""
            if stream_name not in self.streams:
                self.streams[stream_name] = []
            msg_id = f"{len(self.streams[stream_name])}-0"
            self.streams[stream_name].append((msg_id, fields))
            if maxlen and len(self.streams[stream_name]) > maxlen:
                self.streams[stream_name] = self.streams[stream_name][-maxlen:]
            return msg_id

        async def xread(self, streams, count=None, block=None):
            """Read from streams."""
            result = []
            for stream_name, last_id in streams.items():
                if stream_name in self.streams:
                    msgs = [(msg_id, data) for msg_id, data in self.streams[stream_name] if msg_id > last_id]
                    if msgs:
                        result.append([stream_name.encode(), msgs])
            return result if result else None

        async def set(self, key, value, ex=None):
            """Set key-value."""
            self.data[key] = value
            return True

        async def get(self, key):
            """Get value."""
            return self.data.get(key)

        async def delete(self, *keys):
            """Delete keys."""
            count = sum(1 for k in keys if self.data.pop(k, None) is not None)
            return count

        async def exists(self, key):
            """Check if key exists."""
            return 1 if key in self.data else 0

        async def close(self):
            """Close connection."""
            pass

        async def ping(self):
            """Health check."""
            return True

        async def keys(self, pattern):
            """Get keys matching pattern."""
            import re

            # Convert Redis pattern to regex
            if isinstance(pattern, bytes):
                pattern = pattern.decode("utf-8")

            # Redis pattern: * = any chars, ? = one char
            # Convert to regex
            regex_pattern = pattern.replace("*", ".*").replace("?", ".")
            regex = re.compile(f"^{regex_pattern}$")

            # Filter keys
            matching = [k.encode("utf-8") if isinstance(k, str) else k for k in self.data.keys() if regex.match(str(k))]
            return matching

    # Mock Redis adapter connection and messaging methods
    redis_adapter = daemon.client.adapters.get("redis")
    if redis_adapter:
        mock_redis_client = MockRedisClient()
        monkeypatch.setattr(redis_adapter, "redis", mock_redis_client)
        # Mock Redis adapter messaging methods (used by client.send_message for redis-originated sessions)
        monkeypatch.setattr(redis_adapter, "send_message", AsyncMock(return_value="redis-msg-123"))
        monkeypatch.setattr(redis_adapter, "edit_message", AsyncMock(return_value=True))
        monkeypatch.setattr(redis_adapter, "delete_message", AsyncMock())

    # Add db property for test compatibility
    daemon.db = db_module.db

    # Mock Telegram adapter - create mock if not registered (no TELEGRAM_BOT_TOKEN)
    telegram_adapter = daemon.client.adapters.get("telegram")
    if not telegram_adapter:
        # Create a mock telegram adapter that passes isinstance(adapter, UiAdapter)
        # This is needed because AdapterClient.send_output_update() checks isinstance
        from teleclaude.adapters.ui_adapter import UiAdapter
        from teleclaude.core.adapter_client import AdapterClient

        class MockTelegramAdapter(UiAdapter):
            """Mock adapter that passes isinstance check for UiAdapter."""

            def __init__(self, client: AdapterClient) -> None:
                # Call parent init to register event handlers (like _handle_claude_event)
                super().__init__(client)

            # Stub all abstract methods - will be replaced by AsyncMock below
            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_message(self, session, text, metadata):  # type: ignore[override]
                return "msg-123"

            async def edit_message(self, session, message_id, text, metadata):  # type: ignore[override]
                return True

            async def delete_message(self, session, message_id):  # type: ignore[override]
                pass

            async def send_file(self, session, file_path, metadata, caption=None):  # type: ignore[override]
                return "file-msg-789"

            async def create_channel(self, session, title, metadata):  # type: ignore[override]
                return "12345"

            async def update_channel_title(self, session, title):  # type: ignore[override]
                return True

            async def delete_channel(self, session):  # type: ignore[override]
                return True

            async def close_channel(self, session):  # type: ignore[override]
                return True

            async def reopen_channel(self, session):  # type: ignore[override]
                return True

            async def discover_peers(self):  # type: ignore[override]
                return []

            async def poll_output_stream(self, session):  # type: ignore[override]
                pass

        telegram_adapter = MockTelegramAdapter(daemon.client)
        # Replace methods with trackable AsyncMocks
        telegram_adapter.start = AsyncMock()
        telegram_adapter.stop = AsyncMock()
        telegram_adapter.send_message = AsyncMock(return_value="msg-123")
        telegram_adapter.edit_message = AsyncMock(return_value=True)
        telegram_adapter.delete_message = AsyncMock()
        telegram_adapter.send_file = AsyncMock(return_value="file-msg-789")
        telegram_adapter.create_channel = AsyncMock(return_value="12345")
        telegram_adapter.update_channel_title = AsyncMock(return_value=True)
        telegram_adapter.delete_channel = AsyncMock(return_value=True)
        telegram_adapter.send_general_message = AsyncMock(return_value="msg-456")
        telegram_adapter.send_feedback = AsyncMock(return_value="feedback-123")
        telegram_adapter.send_output_update = AsyncMock(return_value="output-msg-123")
        telegram_adapter._cleanup_pending_deletions = AsyncMock()
        daemon.client.adapters["telegram"] = telegram_adapter
    else:
        monkeypatch.setattr(telegram_adapter, "start", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "stop", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "send_message", AsyncMock(return_value="msg-123"))
        monkeypatch.setattr(telegram_adapter, "edit_message", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "delete_message", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "send_file", AsyncMock(return_value="file-msg-789"))
        monkeypatch.setattr(telegram_adapter, "create_channel", AsyncMock(return_value="12345"))
        monkeypatch.setattr(telegram_adapter, "update_channel_title", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "delete_channel", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "send_general_message", AsyncMock(return_value="msg-456"))

    # CRITICAL: Mock terminal_bridge.send_keys to prevent actual command execution
    # Set daemon.mock_command_mode to control behavior:
    # - "short": Quick completion (default)
    # - "long": Long-running interactive process
    daemon.mock_command_mode = "short"
    original_send_keys = terminal_bridge.send_keys

    # Track output files for polling simulation
    output_files_for_session = {}

    async def mock_send_keys(
        session_name: str,
        text: str,
        working_dir: str = "~",
        cols: int = 80,
        rows: int = 24,
        send_enter: bool = True,
    ):
        """Mock send_keys to simulate command execution and output."""
        import uuid

        # Initialize output buffer if needed
        if session_name not in session_outputs:
            session_outputs[session_name] = []

        if daemon.mock_command_mode == "passthrough":
            # Passthrough mode - simulate sending input to running process
            # For long-running process, simulate echo behavior
            if session_outputs[session_name] and "Ready" in session_outputs[session_name]:
                # Process is running, append echo output
                session_outputs[session_name].append(f"Echo: {text}")
            return True, None
        elif daemon.mock_command_mode == "long":
            # Long-running interactive process - append "Ready" to output
            session_outputs[session_name].append("Ready")
            marker_id = f"marker-{uuid.uuid4().hex[:8]}"
            return True, marker_id
        else:
            # Short-lived command - append command echo and simulated output
            # Include the command itself so tests can match on it
            session_outputs[session_name].append(f"$ {text}")
            # For echo commands, simulate the output
            if text.startswith("echo "):
                # Extract text between quotes or just after echo
                echo_text = text[5:].strip().strip("'\"")
                session_outputs[session_name].append(echo_text)
            else:
                session_outputs[session_name].append("Command executed")

            # Generate marker for completion detection
            marker_id = f"marker-{uuid.uuid4().hex[:8]}"

            # Append exit marker to session output (poller reads via capture_pane)
            session_outputs[session_name].append(f"__EXIT__{marker_id}__0__")

            # Write to output file if one exists for polling tests
            # Tests that use polling will register their output file
            if session_name in output_files_for_session:
                output_file = output_files_for_session[session_name]
                # Write command output + exit marker (format: __EXIT__{marker_id}__{exit_code}__)
                with open(output_file, "w") as f:
                    f.write("\n".join(session_outputs[session_name]))

            return True, marker_id

    # Allow tests to register output files for polling simulation
    daemon.register_output_file = lambda session_name, output_file: output_files_for_session.update(
        {session_name: output_file}
    )

    monkeypatch.setattr(terminal_bridge, "send_keys", mock_send_keys)

    # Mock all tmux operations - no real tmux sessions created
    created_sessions = set()
    session_outputs: dict[str, list[str]] = {}  # Track output per session

    async def mock_create_tmux(name: str, working_dir: str, cols: int = 80, rows: int = 24, session_id: str = None):
        """Mock create_tmux_session with same signature as real function."""
        created_sessions.add(name)
        session_outputs[name] = []  # Initialize empty output buffer
        return True

    async def mock_session_exists(session_name: str, log_missing: bool = True):
        """Mock session_exists with same signature as real function."""
        return session_name in created_sessions

    async def mock_kill_session(name):
        created_sessions.discard(name)
        session_outputs.pop(name, None)  # Clean up output buffer
        return True

    async def mock_capture_pane(name):
        # Return accumulated output for this session
        if name not in session_outputs:
            return ""
        return "\n".join(session_outputs[name])

    monkeypatch.setattr(terminal_bridge, "create_tmux_session", mock_create_tmux)
    monkeypatch.setattr(terminal_bridge, "session_exists", mock_session_exists)
    monkeypatch.setattr(terminal_bridge, "kill_session", mock_kill_session)
    monkeypatch.setattr(terminal_bridge, "capture_pane", mock_capture_pane)

    yield daemon

    # Close database connection (temp DB file will be auto-deleted by pytest)
    await daemon.db.close()
