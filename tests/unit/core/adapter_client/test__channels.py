"""Characterization tests for teleclaude.core.adapter_client._channels."""
# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access,too-few-public-methods

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._client import AdapterClient
from teleclaude.core.models import MessageMetadata, Session


def _make_session(
    session_id: str = "sess-1",
    last_input_origin: str = "telegram",
    *,
    closed_at: datetime | None = None,
    lifecycle_status: str = "active",
) -> Session:
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=f"tmux-{session_id}",
        title="Session",
        last_input_origin=last_input_origin,
        closed_at=closed_at,
        lifecycle_status=lifecycle_status,
    )


def _make_ui_adapter() -> MagicMock:
    adapter = MagicMock(spec=UiAdapter)
    adapter.ensure_channel = AsyncMock(side_effect=lambda session: session)  # pyright: ignore[reportUnknownLambdaType]
    adapter.create_channel = AsyncMock(return_value="channel-id")
    adapter.send_message = AsyncMock(return_value="msg-id")
    adapter.send_general_message = AsyncMock(return_value="general-msg")
    adapter._pre_handle_user_input = AsyncMock()
    adapter._post_handle_user_input = AsyncMock()
    adapter.store_channel_id = MagicMock()
    return adapter


def _make_base_adapter() -> MagicMock:
    adapter = MagicMock(spec=BaseAdapter)
    adapter.send_general_message = AsyncMock(return_value="general-msg")
    return adapter


@pytest.fixture(autouse=True)
def _display_title() -> object:  # pyright: ignore[reportUnusedFunction]
    with patch(
        "teleclaude.core.adapter_client._channels.get_display_title_for_session",
        AsyncMock(return_value="Session"),
    ) as mock_title:
        yield mock_title


class TestCommandLifecycleHooks:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pre_handle_command_calls_origin_ui_adapter_pre_handler(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        await client.pre_handle_command(session)

        telegram._pre_handle_user_input.assert_awaited_once_with(session)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_handle_command_calls_origin_ui_adapter_post_handler(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        await client.post_handle_command(session, message_id="msg-1")

        telegram._post_handle_user_input.assert_awaited_once_with(session, "msg-1")


class TestCreateChannel:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_entry_point_channel_id_after_adapter_fanout(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        redis = _make_base_adapter()
        telegram.create_channel = AsyncMock(return_value="42")
        redis.create_channel = AsyncMock(return_value="stream-1")
        client.register_adapter("telegram", telegram)
        client.register_adapter("redis", redis)

        result = await client.create_channel(
            session,
            "Roadmap",
            last_input_origin="telegram",
            target_computer="worker-1",
        )

        assert result == "42"
        telegram.create_channel.assert_awaited_once()
        redis.create_channel.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_entry_point_ui_adapter_fails(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        redis = _make_base_adapter()
        telegram.create_channel = AsyncMock(side_effect=RuntimeError("boom"))
        redis.create_channel = AsyncMock(return_value="stream-1")
        redis.store_channel_id = MagicMock()
        client.register_adapter("telegram", telegram)
        client.register_adapter("redis", redis)

        with pytest.raises(ValueError):
            await client.create_channel(session, "Roadmap", last_input_origin="telegram")


class TestEnsureUiChannels:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_runs_each_ui_adapter_and_returns_refreshed_session(self):
        client = AdapterClient()
        session = _make_session()
        fresh_session = _make_session()
        refreshed_session = _make_session()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch(
            "teleclaude.core.adapter_client._channels.db.get_session",
            AsyncMock(side_effect=[fresh_session, refreshed_session]),
        ):
            result = await client.ensure_ui_channels(session)

        telegram.ensure_channel.assert_awaited_once_with(fresh_session)
        discord.ensure_channel.assert_awaited_once_with(fresh_session)
        assert result is refreshed_session

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_terminal_sessions_without_provisioning_channels(self):
        client = AdapterClient()
        session = _make_session(closed_at=datetime.now(UTC))
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.ensure_ui_channels(session)

        assert result is session
        telegram.ensure_channel.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_provisions_only_included_ui_adapters(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.ensure_ui_channels(session, include_adapters={"telegram"})

        assert result is session
        telegram.ensure_channel.assert_awaited_once_with(session)
        discord.ensure_channel.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_no_ui_adapters_registered(self):
        client = AdapterClient()
        session = _make_session()

        with (
            patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)),
            pytest.raises(ValueError),
        ):
            await client.ensure_ui_channels(session)


class TestSendGeneralMessage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_adapter_not_found(self):
        client = AdapterClient()

        with pytest.raises(ValueError):
            await client.send_general_message("unknown", "text", MessageMetadata())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delegates_to_registered_adapter(self):
        client = AdapterClient()
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        result = await client.send_general_message("telegram", "hello", MessageMetadata())

        assert result == "general-msg"
        telegram.send_general_message.assert_awaited_once_with("hello", metadata=MessageMetadata())
