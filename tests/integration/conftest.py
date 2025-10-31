"""Shared fixtures for integration tests."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from dotenv import load_dotenv
from teleclaude.daemon import TeleClaudeDaemon


@pytest.fixture
async def daemon_with_mocked_telegram(monkeypatch):
    """Create daemon with mocked Telegram adapter and cleanup all resources."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    daemon = TeleClaudeDaemon(
        str(base_dir / "config.yml"),
        str(base_dir / ".env")
    )

    # Mock all Telegram adapter methods
    monkeypatch.setattr(daemon.telegram, "start", AsyncMock())
    monkeypatch.setattr(daemon.telegram, "stop", AsyncMock())
    monkeypatch.setattr(daemon.telegram, "send_message", AsyncMock(return_value="msg-123"))
    monkeypatch.setattr(daemon.telegram, "edit_message", AsyncMock(return_value=True))
    monkeypatch.setattr(daemon.telegram, "create_channel", AsyncMock(return_value="12345"))
    monkeypatch.setattr(daemon.telegram, "update_channel_title", AsyncMock(return_value=True))
    monkeypatch.setattr(daemon.telegram, "send_general_message", AsyncMock(return_value="msg-456"))

    await daemon.session_manager.initialize()
    # Don't actually call start() - it's mocked so calling it does nothing useful
    # Tests can verify it was called if needed with: daemon.telegram.start.assert_called_once()

    yield daemon

    # Cleanup all test sessions and tmux sessions
    sessions = await daemon.session_manager.list_sessions()
    for session in sessions:
        # Kill tmux session if exists
        if await daemon.terminal.session_exists(session.tmux_session_name):
            await daemon.terminal.kill_session(session.tmux_session_name)
        # Delete from database
        await daemon.session_manager.delete_session(session.session_id)

    # Don't call stop() - it's mocked and we never started the real adapter
    await daemon.session_manager.close()
