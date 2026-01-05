"""Unit tests for terminal delivery sink."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.terminal_delivery import deliver_listener_message
from teleclaude.core.ux_state import SessionUXState


@pytest.mark.asyncio
async def test_deliver_listener_message_falls_back_to_tty():
    ux_state = SessionUXState(native_tty_path="/dev/ttys007", native_pid=1234)

    with patch(
        "teleclaude.core.terminal_delivery.terminal_bridge.send_keys_existing_tmux", new=AsyncMock(return_value=False)
    ):
        with patch("teleclaude.core.terminal_delivery.terminal_bridge.pid_is_alive", return_value=True):
            with patch(
                "teleclaude.core.terminal_delivery.terminal_bridge.send_keys_to_tty", new=AsyncMock(return_value=True)
            ):
                with patch("teleclaude.core.terminal_delivery.db.get_ux_state", new=AsyncMock(return_value=ux_state)):
                    with patch("teleclaude.core.terminal_delivery.db.get_session", new=AsyncMock()) as mock_session:
                        mock_session.return_value = type(
                            "Session",
                            (),
                            {"origin_adapter": "terminal", "session_id": "sess-1"},
                        )()
                        delivered = await deliver_listener_message("sess-1", "tmux-1", "hello")

    assert delivered is True
