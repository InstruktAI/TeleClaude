"""Unit tests for terminal delivery sink."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.terminal_delivery import deliver_listener_message


@pytest.mark.asyncio
async def test_deliver_listener_message_returns_false_when_tmux_missing():
    with patch(
        "teleclaude.core.terminal_delivery.terminal_bridge.send_keys_existing_tmux", new=AsyncMock(return_value=False)
    ):
        delivered = await deliver_listener_message("sess-1", "tmux-1", "hello")

    assert delivered is False
