"""Unit tests for terminal_io routing."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import terminal_io
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_send_text_prefers_existing_tmux():
    """Test that send_text targets existing tmux sessions when present."""
    session = Session(
        session_id="sid-123",
        computer_name="test",
        tmux_session_name="telec_123",
        origin_adapter="rest",
        title="Test Terminal",
    )

    with (
        patch.object(terminal_io.terminal_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(
            terminal_io.terminal_bridge,
            "send_keys_existing_tmux",
            new=AsyncMock(return_value=True),
        ) as mock_send_tmux,
        patch.object(terminal_io.terminal_bridge, "send_keys", new=AsyncMock(return_value=True)) as mock_send_keys,
    ):
        ok = await terminal_io.send_text(session, "hello", send_enter=True)

    assert ok is True
    mock_send_tmux.assert_awaited_once()
    mock_send_keys.assert_not_called()


@pytest.mark.asyncio
async def test_send_text_creates_tmux_when_missing():
    """Test that send_text falls back to creating tmux when session missing."""
    session = Session(
        session_id="sid-456",
        computer_name="test",
        tmux_session_name="telec_456",
        origin_adapter="rest",
        title="Test Terminal",
    )

    with (
        patch.object(terminal_io.terminal_bridge, "session_exists", new=AsyncMock(return_value=False)),
        patch.object(
            terminal_io.terminal_bridge,
            "send_keys_existing_tmux",
            new=AsyncMock(return_value=True),
        ) as mock_send_tmux,
        patch.object(terminal_io.terminal_bridge, "send_keys", new=AsyncMock(return_value=True)) as mock_send_keys,
    ):
        ok = await terminal_io.send_text(session, "hello", send_enter=True)

    assert ok is True
    mock_send_tmux.assert_not_called()
    mock_send_keys.assert_awaited_once()
