"""Shared fixtures for integration tests."""

import os
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as redis_asyncio
from dotenv import load_dotenv


class MockRedisClient:
    """Mock Redis client for E2E testing - simulates streams and pub/sub.

    Defined at module level so it can be used by patch() before daemon init.
    """

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[bytes, bytes]]]] = {}
        self.data: dict[str, bytes] = {}

    async def xadd(
        self,
        stream_name: str,
        fields: dict[bytes, bytes],
        maxlen: int | None = None,
        id: str = "*",  # noqa: A002 - Redis API uses 'id'
    ) -> str:
        """Add message to stream."""
        if stream_name not in self.streams:
            self.streams[stream_name] = []
        msg_id = f"{len(self.streams[stream_name])}-0"
        self.streams[stream_name].append((msg_id, fields))
        if maxlen and len(self.streams[stream_name]) > maxlen:
            self.streams[stream_name] = self.streams[stream_name][-maxlen:]
        return msg_id

    async def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[list[object]] | None:
        """Read from streams."""
        result: list[list[object]] = []
        for stream_name, last_id in streams.items():
            if stream_name in self.streams:
                msgs = [(msg_id, data) for msg_id, data in self.streams[stream_name] if msg_id > last_id]
                if msgs:
                    result.append([stream_name.encode(), msgs])
        return result if result else None

    async def set(self, key: str, value: bytes, ex: int | None = None) -> bool:
        """Set key-value."""
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.data[key] = value
        return True

    async def get(self, key: str) -> bytes | None:
        """Get value."""
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        return self.data.get(key)

    async def delete(self, *keys: str) -> int:
        """Delete keys."""
        normalized = [(k.decode("utf-8") if isinstance(k, bytes) else k) for k in keys]
        count = sum(1 for k in normalized if self.data.pop(k, None) is not None)
        return count

    async def exists(self, key: str) -> int:
        """Check if key exists."""
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        return 1 if key in self.data else 0

    async def close(self) -> None:
        """Close connection."""

    async def ping(self) -> bool:
        """Health check."""
        return True

    async def keys(self, pattern: str | bytes) -> list[bytes]:
        """Get keys matching pattern."""
        # Convert Redis pattern to regex
        if isinstance(pattern, bytes):
            pattern = pattern.decode("utf-8")

        # Redis pattern: * = any chars, ? = one char
        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        regex = re.compile(f"^{regex_pattern}$")

        # Filter keys
        matching = [k.encode("utf-8") if isinstance(k, str) else k for k in self.data.keys() if regex.match(str(k))]
        return matching

    async def scan(
        self,
        cursor: int,  # noqa: ARG002 - cursor unused in mock implementation
        match: str | bytes,
        count: int = 100,  # noqa: ARG002 - count unused in mock implementation
    ) -> tuple[int, list[bytes]]:
        """Scan keys matching a pattern (single batch for mock)."""
        matching = await self.keys(match)
        return 0, matching

    async def setex(self, key: str, ttl: int, value: bytes) -> bool:
        """Set key with expiration (expiry ignored for tests)."""
        if isinstance(value, str):
            value = value.encode("utf-8")
        self.data[key] = value
        return True

    async def aclose(self) -> None:
        """Close client (no-op for tests)."""
        return None


@pytest.fixture(scope="function")
async def daemon_with_mocked_telegram(monkeypatch, tmp_path):
    """Create daemon with mocked Telegram adapter and cleanup all resources.

    Function-scoped fixture ensures each test gets isolated database for parallel execution.
    """
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    # CRITICAL: Clear TELEGRAM_BOT_TOKEN immediately after loading .env
    # This prevents real Telegram adapter from starting - we'll use a mock instead
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    # CRITICAL: Set temp database path BEFORE importing teleclaude modules
    # tmp_path is function-scoped, so each test gets unique database automatically
    temp_db_path = str(tmp_path / "test_teleclaude.db")
    monkeypatch.setenv("TELECLAUDE_DB_PATH", temp_db_path)

    # CRITICAL: Set unique REST socket path for parallel execution
    # Keep path short to avoid AF_UNIX length limits on macOS
    temp_rest_socket = f"/tmp/teleclaude-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"

    # NOW import teleclaude modules (after env var is set)
    from teleclaude import api_server as api_server_module
    from teleclaude import config as config_module
    from teleclaude import constants as constants_module
    from teleclaude.core import db as db_module
    from teleclaude.core import tmux_bridge
    from teleclaude.core.db import Db
    from teleclaude.core.session_utils import get_output_file
    from teleclaude.daemon import TeleClaudeDaemon

    # CRITICAL: Patch API_SOCKET_PATH to use unique path per test
    # Also patch api_server module-level constant to avoid stale import values
    monkeypatch.setattr(constants_module, "API_SOCKET_PATH", temp_rest_socket)
    monkeypatch.setattr(api_server_module, "API_SOCKET_PATH", temp_rest_socket)

    # CRITICAL: Mock config exhaustively - ALL sections (no sensitive data)
    class MockDatabase:
        def path(self) -> str:
            return str(tmp_path / "test_teleclaude.db")

    class MockComputer:
        name = "TestComputer"
        default_working_dir = "/tmp"
        default_shell = "/bin/sh"
        tmux_binary = "tmux"
        user = "testuser"
        role = "test"
        host = "test.local"
        timezone = "UTC"
        is_master = False
        trusted_dirs: list[object] = []

        def get_all_trusted_dirs(self) -> list[object]:
            """Return empty list for tests."""
            return []

    class MockPolling:
        directory_check_interval = 5

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
        trusted_bots: list[str] = []

    test_config = type(
        "Config",
        (),
        {
            "database": MockDatabase(),
            "computer": MockComputer(),
            "polling": MockPolling(),
            "redis": MockRedis(),
            "telegram": MockTelegram(),
            "tts": None,
            "agents": {
                "claude": config_module.AgentConfig(
                    command="mock_claude_command --arg",
                    session_dir="~/.claude/sessions",
                    log_pattern="*.jsonl",
                    model_flags={"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"},
                    exec_subcommand="",
                    interactive_flag="-p",
                    non_interactive_flag="-p",
                    resume_template="{base_cmd} --resume {session_id}",
                    continue_template="",
                ),
                "gemini": config_module.AgentConfig(
                    command="mock_gemini_command --arg",
                    session_dir="~/.gemini/sessions",
                    log_pattern="*.jsonl",
                    model_flags={
                        "fast": "-m gemini-2.5-flash-lite",
                        "med": "-m gemini-2.5-flash",
                        "slow": "-m gemini-3-pro-preview",
                    },
                    exec_subcommand="",
                    interactive_flag="-i",
                    non_interactive_flag="",
                    resume_template="{base_cmd} --resume {session_id}",
                    continue_template="",
                ),
                "codex": config_module.AgentConfig(
                    command="mock_codex_command --arg",
                    session_dir="~/.codex/sessions",
                    log_pattern="*.jsonl",
                    model_flags={
                        "fast": "-m gpt-5.1-codex-mini",
                        "med": "-m gpt-5.1-codex",
                        "slow": "-m gpt-5.3",
                    },
                    exec_subcommand="exec",
                    interactive_flag="",
                    non_interactive_flag="",
                    resume_template="{base_cmd} resume {session_id}",
                    continue_template="",
                ),
            },
        },
    )()

    monkeypatch.setattr(config_module, "config", test_config)

    monkeypatch.setattr(config_module.config.redis, "url", "redis://localhost:6379")

    rest_socket_path = f"/tmp/teleclaude-api-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock"
    monkeypatch.setattr(constants_module, "API_SOCKET_PATH", rest_socket_path)
    monkeypatch.setattr(api_server_module, "API_SOCKET_PATH", rest_socket_path)

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
        "teleclaude.transport.redis_transport",
        "teleclaude.daemon",
        "teleclaude.mcp_server",
        "teleclaude.mcp.handlers",
        "teleclaude.core.polling_coordinator",
        "teleclaude.core.command_handlers",
        "teleclaude.core.session_cleanup",
        "teleclaude.services.maintenance_service",
        "teleclaude.adapters.ui_adapter",
        "teleclaude.core.file_handler",
        "teleclaude.core.session_utils",
        "teleclaude.core.voice_message_handler",
        "teleclaude.core.agent_coordinator",
        "teleclaude.tts.manager",
    ]

    for module_name in modules_to_patch:
        monkeypatch.setattr(f"{module_name}.db", db_module.db)

    # Patch config only in modules that actually import it
    config_modules = [
        "teleclaude.core.adapter_client",
        "teleclaude.core.command_handlers",
        "teleclaude.core.db",
        "teleclaude.core.output_poller",
        "teleclaude.transport.redis_transport",
        "teleclaude.adapters.telegram_adapter",
        "teleclaude.adapters.ui_adapter",
        "teleclaude.daemon",
        "teleclaude.mcp_server",
        "teleclaude.tts.manager",
    ]

    for module_name in config_modules:
        monkeypatch.setattr(f"{module_name}.config", test_config)

    # Reset cached TTS manager to ensure patched config/db are used
    from teleclaude.core import voice_assignment as voice_assignment_module

    voice_assignment_module._tts_manager = None

    # CRITICAL: Patch Redis.from_url and TelegramAdapter BEFORE daemon/adapter initialization
    # This prevents real network calls to Redis and Telegram
    mock_redis_client = MockRedisClient()

    # Create mock Telegram adapter class that will be used instead of real one
    from teleclaude.adapters.ui_adapter import UiAdapter
    from teleclaude.core.adapter_client import AdapterClient as AC

    class MockTelegramAdapter(UiAdapter):
        """Mock adapter that passes isinstance check for UiAdapter."""

        ADAPTER_KEY = "telegram"

        def __init__(self, client: AC) -> None:
            super().__init__(client)

        async def start(self) -> None:
            pass  # No real Telegram API calls

        async def stop(self) -> None:
            pass

        async def send_message(
            self, session: object, text: str, metadata: object = None, multi_message: bool = False
        ) -> str:
            return "msg-123"

        async def edit_message(self, session: object, message_id: str, text: str, metadata: object) -> bool:
            return True

        async def delete_message(self, session: object, message_id: str) -> bool:
            return True

        async def send_file(self, session: object, file_path: str, metadata: object, caption: str | None = None) -> str:
            return "file-msg-789"

        async def create_channel(self, session: object, title: str, metadata: object) -> str:
            return "12345"

        async def update_channel_title(self, session: object, title: str) -> bool:
            return True

        async def delete_channel(self, session: object) -> bool:
            return True

        async def close_channel(self, session: object) -> bool:
            return True

        async def reopen_channel(self, session: object) -> bool:
            return True

        async def discover_peers(self) -> list[object]:
            return []

        async def poll_output_stream(self, session: object, timeout: float = 300.0) -> None:  # type: ignore[override]
            pass

        async def _pre_handle_user_input(self, session: object) -> None:
            """Delete pending messages on user input (like real TelegramAdapter)."""
            from teleclaude.core.db import db as test_db

            pending = await test_db.get_pending_deletions(session.session_id)  # type: ignore[union-attr]
            if pending:
                for msg_id in pending:
                    try:
                        await self.delete_message(session, msg_id)
                    except Exception:
                        pass  # Resilient to already-deleted messages
                await test_db.clear_pending_deletions(session.session_id)  # type: ignore[union-attr]

    def _mock_from_url(*_args, **_kwargs):
        return mock_redis_client

    monkeypatch.setattr(redis_asyncio.Redis, "from_url", classmethod(_mock_from_url))
    monkeypatch.setattr("teleclaude.core.adapter_client.TelegramAdapter", MockTelegramAdapter)
    monkeypatch.setattr(
        "teleclaude.transport.redis_transport.RedisTransport._poll_redis_messages",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "teleclaude.transport.redis_transport.RedisTransport._heartbeat_loop",
        AsyncMock(return_value=None),
    )

    # Create daemon (config is loaded automatically from config.yml)
    daemon = TeleClaudeDaemon(str(base_dir / ".env"))

    # Start adapters - this will use mocked Redis and mocked TelegramAdapter
    await daemon.client.start()

    # Add db property for test compatibility
    daemon.db = db_module.db

    # Mock Redis adapter messaging methods (used by client.send_message for redis-originated sessions)
    redis_adapter = daemon.client.adapters.get("redis")
    if redis_adapter:
        monkeypatch.setattr(redis_adapter, "send_message", AsyncMock(return_value="redis-msg-123"))
        monkeypatch.setattr(redis_adapter, "edit_message", AsyncMock(return_value=True))
        monkeypatch.setattr(redis_adapter, "delete_message", AsyncMock())

    # Replace Telegram adapter methods with trackable AsyncMocks
    telegram_adapter = daemon.client.adapters.get("telegram")
    if telegram_adapter:
        telegram_adapter.start = AsyncMock()  # type: ignore[method-assign]
        telegram_adapter.stop = AsyncMock()  # type: ignore[method-assign]
        telegram_adapter.send_message = AsyncMock(return_value="msg-123")  # type: ignore[method-assign]
        telegram_adapter.edit_message = AsyncMock(return_value=True)  # type: ignore[method-assign]
        telegram_adapter.delete_message = AsyncMock()  # type: ignore[method-assign]
        telegram_adapter.send_file = AsyncMock(return_value="file-msg-789")  # type: ignore[method-assign]
        telegram_adapter.create_channel = AsyncMock(return_value="12345")  # type: ignore[method-assign]
        telegram_adapter.update_channel_title = AsyncMock(return_value=True)  # type: ignore[method-assign]
        telegram_adapter.delete_channel = AsyncMock(return_value=True)  # type: ignore[method-assign]
        telegram_adapter.send_general_message = AsyncMock(return_value="msg-456")  # type: ignore[method-assign]
        telegram_adapter.send_feedback = AsyncMock(return_value="feedback-123")  # type: ignore[method-assign]
        telegram_adapter.send_output_update = AsyncMock(return_value="output-msg-123")  # type: ignore[method-assign]
        telegram_adapter._cleanup_pending_deletions = AsyncMock()  # type: ignore[method-assign]

    # CRITICAL: Mock tmux_bridge.send_keys to prevent actual command execution
    # Set daemon.mock_command_mode to control behavior:
    # - "short": Quick completion (default)
    # - "long": Long-running interactive process
    daemon.mock_command_mode = "short"

    # Track output files for polling simulation
    output_files_for_session = {}
    session_ids_by_name: dict[str, str] = {}

    def _resolve_output_file(session_name: str, session_id: str | None) -> Path | None:
        if session_id:
            return get_output_file(session_id)
        if session_name in session_ids_by_name:
            return get_output_file(session_ids_by_name[session_name])
        if session_name in output_files_for_session:
            return Path(output_files_for_session[session_name])
        return None

    def _append_output(session_name: str, session_id: str | None, lines: list[str]) -> None:
        if not lines:
            return
        output_file = _resolve_output_file(session_name, session_id)
        if not output_file:
            return
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")

    async def mock_send_keys(
        session_name: str,
        text: str,
        session_id: str | None = None,
        working_dir: str = "~",
        cols: int = 80,
        rows: int = 24,
        send_enter: bool = True,
        active_agent: str | None = None,
    ):
        """Mock send_keys to simulate command execution and output."""

        # Initialize output buffer if needed
        if session_name not in session_outputs:
            session_outputs[session_name] = []
        if session_name not in process_running:
            process_running[session_name] = False

        new_lines: list[str] = []

        if daemon.mock_command_mode == "passthrough":
            # Passthrough mode - simulate sending input to running process
            # For long-running process, simulate echo behavior
            process_running[session_name] = True
            if session_outputs[session_name] and "Ready" in session_outputs[session_name]:
                # Process is running, append echo output
                session_outputs[session_name].append(f"Echo: {text}")
                new_lines.append(f"Echo: {text}")
            _append_output(session_name, session_id, new_lines)
            return True
        elif daemon.mock_command_mode == "long":
            # Long-running interactive process - append "Ready" to output
            session_outputs[session_name].append("Ready")
            new_lines.append("Ready")
            process_running[session_name] = True
            _append_output(session_name, session_id, new_lines)
            return True
        else:
            # Short-lived command - append command echo and simulated output
            # Include the command itself so tests can match on it
            session_outputs[session_name].append(f"$ {text}")
            new_lines.append(f"$ {text}")
            # For echo commands, simulate the output
            if text.startswith("echo "):
                # Extract text between quotes or just after echo
                echo_text = text[5:].strip().strip("'\"")
                session_outputs[session_name].append(echo_text)
                new_lines.append(echo_text)
            else:
                session_outputs[session_name].append("Command executed")
                new_lines.append("Command executed")
            process_running[session_name] = False

            _append_output(session_name, session_id, new_lines)

            return True

    # Allow tests to register output files for polling simulation
    daemon.register_output_file = lambda session_name, output_file: output_files_for_session.update(
        {session_name: output_file}
    )

    async def mock_send_keys_existing_tmux(
        session_name: str,
        text: str,
        *,
        send_enter: bool = True,
        active_agent: str | None = None,
    ):
        session_id = session_ids_by_name.get(session_name)
        return await mock_send_keys(
            session_name,
            text,
            session_id=session_id,
            send_enter=send_enter,
            active_agent=active_agent,
        )

    monkeypatch.setattr(tmux_bridge, "send_keys", mock_send_keys)
    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", mock_send_keys_existing_tmux)

    # Mock all tmux operations - no real tmux sessions created
    created_sessions = set()
    session_outputs: dict[str, list[str]] = {}  # Track output per session
    process_running: dict[str, bool] = {}

    async def mock_create_tmux(
        name: str,
        working_dir: str,
        cols: int = 80,
        rows: int = 24,
        session_id: str = None,
        env_vars: dict = None,
    ):
        """Mock create_tmux_session with same signature as real function."""
        created_sessions.add(name)
        if session_id:
            session_ids_by_name[name] = session_id
        if name not in session_outputs:
            session_outputs[name] = []  # Initialize empty output buffer
        if name not in process_running:
            process_running[name] = False
        return True

    async def mock_session_exists(session_name: str, log_missing: bool = True):
        """Mock session_exists with same signature as real function."""
        return session_name in created_sessions

    async def mock_ensure_tmux_session(
        name: str,
        *,
        working_dir: str = "~",
        session_id: str = None,
        env_vars: dict = None,
    ):
        if name in created_sessions:
            return True
        return await mock_create_tmux(
            name=name,
            working_dir=working_dir,
            session_id=session_id,
            env_vars=env_vars,
        )

    async def mock_kill_session(name):
        created_sessions.discard(name)
        session_outputs.pop(name, None)  # Clean up output buffer
        process_running.pop(name, None)
        return True

    async def mock_capture_pane(name, lines=None):
        # Return accumulated output for this session
        if name not in session_outputs:
            return ""
        output = "\n".join(session_outputs[name])
        if lines is None:
            return output
        if lines <= 0:
            return output
        return "\n".join(output.splitlines()[-lines:])

    async def mock_is_process_running(name):
        return process_running.get(name, False)

    async def mock_get_pane_tty(_name: str):
        return None

    async def mock_get_pane_pid(_name: str):
        return None

    monkeypatch.setattr(tmux_bridge, "_create_tmux_session", mock_create_tmux)
    monkeypatch.setattr(tmux_bridge, "ensure_tmux_session", mock_ensure_tmux_session)
    monkeypatch.setattr(tmux_bridge, "session_exists", mock_session_exists)
    monkeypatch.setattr(tmux_bridge, "kill_session", mock_kill_session)
    monkeypatch.setattr(tmux_bridge, "capture_pane", mock_capture_pane)
    monkeypatch.setattr(tmux_bridge, "is_process_running", mock_is_process_running)
    monkeypatch.setattr(tmux_bridge, "start_pipe_pane", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "get_pane_tty", mock_get_pane_tty)
    monkeypatch.setattr(tmux_bridge, "get_pane_pid", mock_get_pane_pid)

    try:
        yield daemon
    finally:
        # Stop daemon to cancel background pollers before pytest-timeout triggers
        await daemon.stop()
        # Close the aiosqlite connection to avoid lingering worker threads that
        # can keep pytest alive after tests complete.
        await db_module.db.close()
