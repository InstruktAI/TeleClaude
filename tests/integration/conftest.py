"""Shared fixtures for integration tests."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from dotenv import load_dotenv
from teleclaude import config as config_module
from teleclaude.core import terminal_bridge
from teleclaude.daemon import TeleClaudeDaemon


@pytest.fixture
async def daemon_with_mocked_telegram(monkeypatch, tmp_path):
    """Create daemon with mocked Telegram adapter and cleanup all resources."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    # Use temp database for this test to prevent session accumulation
    import os
    temp_db_path = str(tmp_path / "test_teleclaude.db")
    monkeypatch.setenv("TELECLAUDE_DB_PATH", temp_db_path)

    # Create daemon (config is loaded automatically from config.yml)
    daemon = TeleClaudeDaemon(str(base_dir / ".env"))

    # Add db property for test compatibility (daemon uses module-level db now)
    from teleclaude.core.db import db
    daemon.db = db

    # Mock all Telegram adapter methods (access via client.adapters["telegram"])
    telegram_adapter = daemon.client.adapters.get("telegram")
    if telegram_adapter:
        monkeypatch.setattr(telegram_adapter, "start", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "stop", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "send_message", AsyncMock(return_value="msg-123"))
        monkeypatch.setattr(telegram_adapter, "edit_message", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "delete_message", AsyncMock())
        monkeypatch.setattr(telegram_adapter, "create_channel", AsyncMock(return_value="12345"))
        monkeypatch.setattr(telegram_adapter, "update_channel_title", AsyncMock(return_value=True))
        monkeypatch.setattr(telegram_adapter, "send_general_message", AsyncMock(return_value="msg-456"))

    await daemon.db.initialize()

    # Clean up any leftover sessions from previous test runs
    old_sessions = await daemon.db.list_sessions()
    for session in old_sessions:
        if await terminal_bridge.session_exists(session.tmux_session_name):
            await terminal_bridge.kill_session(session.tmux_session_name)
        await daemon.db.delete_session(session.session_id)

    # Don't actually call start() - it's mocked so calling it does nothing useful
    # Tests can verify it was called if needed with: daemon.client.adapters["telegram"].start.assert_called_once()

    yield daemon

    # Cleanup all test sessions and tmux sessions
    sessions = await daemon.db.list_sessions()
    for session in sessions:
        # Kill tmux session if exists
        if await terminal_bridge.session_exists(session.tmux_session_name):
            await terminal_bridge.kill_session(session.tmux_session_name)
        # Delete from database
        await daemon.db.delete_session(session.session_id)

    # Don't call stop() - it's mocked and we never started the real adapter
    await daemon.db.close()
