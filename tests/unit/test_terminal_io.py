"""Unit tests for terminal_io routing."""

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core import terminal_io
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_send_text_prefers_existing_tmux():
    session = Session(
        session_id="sid-123",
        computer_name="test",
        tmux_session_name="telec_123",
        origin_adapter="terminal",
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
    session = Session(
        session_id="sid-456",
        computer_name="test",
        tmux_session_name="telec_456",
        origin_adapter="terminal",
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
