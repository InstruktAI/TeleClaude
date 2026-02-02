"""Unit tests for tmux_io routing."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import tmux_io
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_send_text_prefers_existing_tmux():
    """Test that send_text targets existing tmux sessions when present."""
    session = Session(
        session_id="sid-123",
        computer_name="test",
        tmux_session_name="telec_123",
        last_input_origin=InputOrigin.API.value,
        title="Test Tmux",
    )

    with (
        patch.object(tmux_io.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(
            tmux_io.tmux_bridge,
            "send_keys_existing_tmux",
            new=AsyncMock(return_value=True),
        ) as mock_send_tmux,
    ):
        ok = await tmux_io.send_text(session, "hello", send_enter=True, working_dir="/tmp")

        assert ok is True
        assert mock_send_tmux.await_count == 1


@pytest.mark.asyncio
async def test_send_text_creates_tmux_when_missing():
    """Test that send_text falls back to creating tmux when session missing."""
    session = Session(
        session_id="sid-456",
        computer_name="test",
        tmux_session_name="telec_456",
        last_input_origin=InputOrigin.API.value,
        title="Test Tmux",
    )

    with (
        patch.object(tmux_io.tmux_bridge, "session_exists", new=AsyncMock(return_value=False)),
        patch.object(tmux_io.tmux_bridge, "send_keys", new=AsyncMock(return_value=True)) as mock_send_keys,
    ):
        ok = await tmux_io.send_text(session, "hello", send_enter=True, working_dir="/tmp")

        assert ok is True
        assert mock_send_keys.await_count == 1
