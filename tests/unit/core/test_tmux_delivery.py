"""Characterization tests for teleclaude.core.tmux_delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core import tmux_delivery
from teleclaude.core.tmux_delivery import (
    LISTENER_DELIVERY_TIMEOUT_S,
    LISTENER_RETRY_BACKOFF_S,
    deliver_listener_message,
)


class TestDeliverListenerMessage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_first_attempt_success_returns_true_without_sleep(self) -> None:
        with (
            patch.object(tmux_delivery, "tmux_bridge") as mock_bridge,
            patch.object(tmux_delivery.asyncio, "sleep", new=AsyncMock()) as mock_sleep,
        ):
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=True)
            result = await deliver_listener_message("sess-001", "tc-session", "hello")

        assert result is True
        assert mock_bridge.send_keys_existing_tmux.await_count == 1
        mock_sleep.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_message_and_timeout_are_forwarded_to_tmux(self) -> None:
        with (
            patch.object(tmux_delivery, "tmux_bridge") as mock_bridge,
            patch.object(tmux_delivery.asyncio, "sleep", new=AsyncMock()),
        ):
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=True)
            await deliver_listener_message("sess-001", "tmux-name", "test message")

            kwargs = mock_bridge.send_keys_existing_tmux.call_args.kwargs
            assert kwargs["session_name"] == "tmux-name"
            assert kwargs["text"] == "test message"
            assert kwargs["timeout"] == LISTENER_DELIVERY_TIMEOUT_S

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retry_then_success_returns_true(self) -> None:
        with (
            patch.object(tmux_delivery, "tmux_bridge") as mock_bridge,
            patch.object(tmux_delivery.asyncio, "sleep", new=AsyncMock()) as mock_sleep,
        ):
            mock_bridge.send_keys_existing_tmux = AsyncMock(side_effect=[False, False, True])
            result = await deliver_listener_message("sess-001", "tmux-name", "hello")

        assert result is True
        assert mock_bridge.send_keys_existing_tmux.await_count == 3
        # One sleep between attempt 1→2 and one between 2→3.
        assert [call.args[0] for call in mock_sleep.await_args_list] == list(LISTENER_RETRY_BACKOFF_S[:2])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_persistent_failure_exhausts_retries_and_returns_false(self) -> None:
        with (
            patch.object(tmux_delivery, "tmux_bridge") as mock_bridge,
            patch.object(tmux_delivery.asyncio, "sleep", new=AsyncMock()) as mock_sleep,
        ):
            mock_bridge.send_keys_existing_tmux = AsyncMock(return_value=False)
            result = await deliver_listener_message("sess-001", "tmux-name", "hello")

        assert result is False
        total_attempts = len(LISTENER_RETRY_BACKOFF_S) + 1
        assert mock_bridge.send_keys_existing_tmux.await_count == total_attempts
        # Sleep fires between attempts only — never after the final attempt.
        assert [call.args[0] for call in mock_sleep.await_args_list] == list(LISTENER_RETRY_BACKOFF_S)
