"""Characterization tests for teleclaude.core.adapter_client._client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._client import AdapterClient
from teleclaude.core.models import Session


def _make_ui_adapter(*, threaded: bool = False) -> MagicMock:
    adapter = MagicMock(spec=UiAdapter)
    adapter.THREADED_OUTPUT = threaded
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    return adapter


def _make_base_adapter() -> MagicMock:
    adapter = MagicMock(spec=BaseAdapter)
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    return adapter


def _make_session(session_id: str = "sess-1", last_input_origin: str = "telegram") -> Session:
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=f"tmux-{session_id}",
        title="Session",
        last_input_origin=last_input_origin,
    )


class TestInit:
    @pytest.mark.unit
    def test_starts_with_expected_defaults(self):
        client = AdapterClient()

        assert client.adapters == {}
        assert client.is_shutting_down is False
        assert client.agent_event_handler is None
        assert client.agent_coordinator is None
        assert client._channel_ensure_locks == {}

    @pytest.mark.unit
    def test_stores_task_registry(self):
        registry = MagicMock()

        client = AdapterClient(task_registry=registry)

        assert client.task_registry is registry


class TestMarkShuttingDown:
    @pytest.mark.unit
    def test_sets_shutdown_flag(self):
        client = AdapterClient()

        client.mark_shutting_down()

        assert client.is_shutting_down is True


class TestRegisterAdapter:
    @pytest.mark.unit
    def test_stores_adapter_by_type(self):
        client = AdapterClient()
        adapter = _make_base_adapter()

        client.register_adapter("telegram", adapter)

        assert client.adapters["telegram"] is adapter

    @pytest.mark.unit
    def test_overwrites_existing_adapter(self):
        client = AdapterClient()
        adapter_1 = _make_base_adapter()
        adapter_2 = _make_base_adapter()

        client.register_adapter("telegram", adapter_1)
        client.register_adapter("telegram", adapter_2)

        assert client.adapters["telegram"] is adapter_2


class TestAnyAdapterWantsThreadedOutput:
    @pytest.mark.unit
    def test_returns_false_without_ui_adapters(self):
        client = AdapterClient()

        assert client.any_adapter_wants_threaded_output() is False

    @pytest.mark.unit
    def test_returns_true_when_any_ui_adapter_uses_threaded_output(self):
        client = AdapterClient()
        client.register_adapter("telegram", _make_ui_adapter(threaded=False))
        client.register_adapter("discord", _make_ui_adapter(threaded=True))

        assert client.any_adapter_wants_threaded_output() is True


class TestStart:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_when_no_adapters_start(self):
        client = AdapterClient()
        disabled_config = SimpleNamespace(
            discord=SimpleNamespace(enabled=False),
            whatsapp=SimpleNamespace(enabled=False, phone_number_id=None, access_token=None),
            redis=SimpleNamespace(enabled=False),
        )

        with (
            patch("teleclaude.core.adapter_client._client.config", disabled_config),
            patch("teleclaude.core.adapter_client._client.os.getenv", return_value=None),
            pytest.raises(ValueError),
        ):
            await client.start()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_starts_and_registers_enabled_adapters(self):
        registry = MagicMock()
        client = AdapterClient(task_registry=registry)
        config = SimpleNamespace(
            discord=SimpleNamespace(enabled=True),
            whatsapp=SimpleNamespace(enabled=False, phone_number_id=None, access_token=None),
            redis=SimpleNamespace(enabled=True),
        )
        discord_adapter = _make_ui_adapter(threaded=True)
        telegram_adapter = _make_ui_adapter(threaded=False)
        redis_adapter = _make_base_adapter()

        def fake_getenv(key: str) -> str | None:
            if key == "TELEGRAM_BOT_TOKEN":
                return "telegram-token"
            return None

        with (
            patch("teleclaude.core.adapter_client._client.config", config),
            patch("teleclaude.core.adapter_client._client.os.getenv", side_effect=fake_getenv),
            patch(
                "teleclaude.core.adapter_client._client.DiscordAdapter", return_value=discord_adapter
            ) as discord_ctor,
            patch(
                "teleclaude.core.adapter_client._client.TelegramAdapter", return_value=telegram_adapter
            ) as telegram_ctor,
            patch("teleclaude.core.adapter_client._client.RedisTransport", return_value=redis_adapter) as redis_ctor,
        ):
            await client.start()

        assert client.adapters == {
            "discord": discord_adapter,
            "telegram": telegram_adapter,
            "redis": redis_adapter,
        }
        discord_ctor.assert_called_once_with(client, task_registry=registry)
        telegram_ctor.assert_called_once_with(client)
        redis_ctor.assert_called_once_with(client, task_registry=registry)
        discord_adapter.start.assert_awaited_once()
        telegram_adapter.start.assert_awaited_once()
        redis_adapter.start.assert_awaited_once()


class TestStop:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_calls_stop_on_all_registered_adapters(self):
        client = AdapterClient()
        telegram = _make_base_adapter()
        redis = _make_base_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("redis", redis)

        await client.stop()

        telegram.stop.assert_awaited_once()
        redis.stop.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_continues_when_one_adapter_stop_fails(self):
        client = AdapterClient()
        failing = _make_base_adapter()
        healthy = _make_base_adapter()
        failing.stop = AsyncMock(side_effect=RuntimeError("boom"))
        client.register_adapter("telegram", failing)
        client.register_adapter("redis", healthy)

        await client.stop()

        healthy.stop.assert_awaited_once()


class TestPublicClientState:
    @pytest.mark.unit
    def test_registered_ui_adapters_affect_threaded_output_flag(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter(threaded=False)
        discord = _make_ui_adapter(threaded=True)
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        assert client.any_adapter_wants_threaded_output() is True
        assert session.last_input_origin == "telegram"
