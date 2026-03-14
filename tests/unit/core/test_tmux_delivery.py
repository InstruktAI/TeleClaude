"""Characterization tests for teleclaude.core.tmux_delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.tmux_delivery import deliver_listener_message


class TestDeliverListenerMessage:
    @pytest.mark.unit
    async def test_successful_delivery_returns_true(self):
        with patch("teleclaude.core.tmux_delivery.tmux_bridge") as mock_bridge:
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=True)
            result = await deliver_listener_message("sess-001", "tc-session", "hello")
        assert result is True

    @pytest.mark.unit
    async def test_failed_delivery_returns_false(self):
        with patch("teleclaude.core.tmux_delivery.tmux_bridge") as mock_bridge:
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=False)
            result = await deliver_listener_message("sess-001", "tc-session", "hello")
        assert result is False

    @pytest.mark.unit
    async def test_message_forwarded_to_tmux(self):
        with patch("teleclaude.core.tmux_delivery.tmux_bridge") as mock_bridge:
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=True)
            await deliver_listener_message("sess-001", "tmux-name", "test message")
            mock_bridge.send_keys_existing_tmux.assert_called_once()
            call_kwargs = mock_bridge.send_keys_existing_tmux.call_args
            assert call_kwargs.kwargs.get("session_name") == "tmux-name"
