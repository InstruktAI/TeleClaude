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
    from teleclaude.core import db as db_module
    from teleclaude.core import terminal_bridge
    from teleclaude.core.db import Db
    from teleclaude.daemon import TeleClaudeDaemon

    # CRITICAL: Reinitialize db singleton with test database path
    # This ensures each test gets isolated database even in parallel execution
    db_module.db = Db(temp_db_path)
    await db_module.db.initialize()

    # CRITICAL: Patch db singleton in ALL modules that imported it at module load time
    # Without this, modules keep reference to old uninitialized db instance
    modules_to_patch = [
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

    # Create daemon (config is loaded automatically from config.yml)
    daemon = TeleClaudeDaemon(str(base_dir / ".env"))

    # Add db property for test compatibility
    daemon.db = db_module.db

    # Mock all Telegram adapter methods (access via client.adapters["telegram"])
    telegram_adapter = daemon.client.adapters.get("telegram")
    if telegram_adapter:
        monkeypatch.setattr(telegram_adapter, "start", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "stop", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "send_message", AsyncMock(return_value="msg-123"))
        monkeypatch.setattr(telegram_adapter, "edit_message", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "delete_message", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "send_file", AsyncMock(return_value="file-msg-789"))
        monkeypatch.setattr(telegram_adapter, "create_channel", AsyncMock(return_value="12345"))
        monkeypatch.setattr(telegram_adapter, "update_channel_title", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "send_general_message", AsyncMock(return_value="msg-456"))

    # CRITICAL: Mock terminal_bridge.send_keys to prevent actual command execution
    # Set daemon.mock_command_mode to control behavior:
    # - "short": Quick completion (default)
    # - "long": Long-running interactive process
    daemon.mock_command_mode = "short"
    original_send_keys = terminal_bridge.send_keys

    async def mock_send_keys(
        session_name: str,
        text: str,
        working_dir: str = "~",
        cols: int = 80,
        rows: int = 24,
        send_enter: bool = True,
    ):
        """Mock send_keys to replace commands based on configured mode."""
        if daemon.mock_command_mode == "passthrough":
            # Passthrough mode - don't mock, send original text
            return await original_send_keys(session_name, text, working_dir, cols, rows, send_enter)
        elif daemon.mock_command_mode == "long":
            # Long-running interactive process that waits for input
            mock_command = "python3 -c \"import sys; print('Ready', flush=True); [print(f'Echo: {line.strip()}', flush=True) for line in sys.stdin]\""
        else:
            # Short-lived command (instant completion)
            mock_command = "echo 'Command executed'"

        return await original_send_keys(session_name, mock_command, working_dir, cols, rows, send_enter)

    monkeypatch.setattr(terminal_bridge, "send_keys", mock_send_keys)

    # Clean up any leftover sessions from previous test runs
    # ONLY clean up sessions that are in the test database (temp db)
    old_sessions = await daemon.db.list_sessions()
    for session in old_sessions:
        # Only kill tmux sessions that start with 'test-' prefix
        if session.tmux_session_name.startswith("test-"):
            if await terminal_bridge.session_exists(session.tmux_session_name):
                await terminal_bridge.kill_session(session.tmux_session_name)
        await daemon.db.delete_session(session.session_id)

    # Don't actually call start() - it's mocked so calling it does nothing useful
    # Tests can verify it was called if needed with: daemon.client.adapters["telegram"].start.assert_called_once()

    yield daemon

    # Cleanup all test sessions and tmux sessions
    # ONLY clean up sessions that are in the test database
    sessions = await daemon.db.list_sessions()
    for session in sessions:
        # Only kill tmux sessions that start with 'test-' prefix
        if session.tmux_session_name.startswith("test-"):
            if await terminal_bridge.session_exists(session.tmux_session_name):
                await terminal_bridge.kill_session(session.tmux_session_name)
        # Delete from test database
        await daemon.db.delete_session(session.session_id)

    # Don't call stop() - it's mocked and we never started the real adapter
    await daemon.db.close()
