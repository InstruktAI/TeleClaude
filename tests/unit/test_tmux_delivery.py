"""Unit tests for terminal delivery sink."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.tmux_delivery import deliver_listener_message


@pytest.mark.asyncio
async def test_deliver_listener_message_returns_false_when_tmux_missing():
    """Test that delivery returns False when tmux session cannot be used."""
    with patch("teleclaude.core.tmux_delivery.tmux_bridge.send_keys_existing_tmux", new=AsyncMock(return_value=False)):
        delivered = await deliver_listener_message("sess-1", "tmux-1", "hello")

    assert delivered is False
