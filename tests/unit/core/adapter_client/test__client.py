"""Characterization tests for teleclaude.core.adapter_client._client."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._client import AdapterClient, AdapterStatus


def _make_ui_adapter() -> MagicMock:
    adapter = MagicMock(spec=UiAdapter)
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    return adapter


def _make_base_adapter() -> MagicMock:
    adapter = MagicMock(spec=BaseAdapter)
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    return adapter


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


class TestResolveUiTargets:
    @pytest.mark.unit
    def test_returns_registered_ui_adapters(self) -> None:
        client = AdapterClient()
        client.register_adapter("discord", _make_ui_adapter())
        assert [t for t, _ in client._resolve_ui_targets()] == ["discord"]

    @pytest.mark.unit
    def test_include_filter_narrows_to_empty_when_unmatched(self) -> None:
        client = AdapterClient()
        client.register_adapter("discord", _make_ui_adapter())
        assert client._resolve_ui_targets(include_adapters={"telegram"}) == []


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


def _fake_validator_env(**values: str) -> AbstractContextManager[MagicMock]:
    """Patch the validator's env lookup with the given VAR→value mapping."""

    def _getenv(key: str, default: str = "") -> str:
        return values.get(key, default)

    return patch("teleclaude.config.adapter_validation.os.getenv", side_effect=_getenv)


class TestStart:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_starts_enabled_and_configured_adapters(self):
        registry = MagicMock()
        client = AdapterClient(task_registry=registry)
        config = SimpleNamespace(
            discord=SimpleNamespace(enabled=True, token="discord-token"),
            telegram=SimpleNamespace(enabled=True),  # token resolves from env
            whatsapp=SimpleNamespace(enabled=False, phone_number_id=None, access_token=None),
        )
        discord_adapter = _make_ui_adapter()
        telegram_adapter = _make_ui_adapter()
        redis_adapter = _make_base_adapter()

        with (
            patch("teleclaude.core.adapter_client._client.config", config),
            _fake_validator_env(TELEGRAM_BOT_TOKEN="telegram-token"),
            patch("teleclaude.core.adapter_client._client.DiscordAdapter", return_value=discord_adapter),
            patch("teleclaude.core.adapter_client._client.TelegramAdapter", return_value=telegram_adapter),
            patch("teleclaude.core.adapter_client._client.RedisTransport", return_value=redis_adapter),
        ):
            await client.start()

        # Redis is a transport, not an adapter — it lives on client.transport.
        assert client.adapters == {"discord": discord_adapter, "telegram": telegram_adapter}
        assert client.transport is redis_adapter
        assert client.adapter_status["discord"].status == AdapterStatus.OK
        assert client.adapter_status["telegram"].status == AdapterStatus.OK
        assert client.adapter_status["whatsapp"].status == AdapterStatus.DISABLED
        discord_adapter.start.assert_awaited_once()
        telegram_adapter.start.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enabled_but_unconfigured_adapter_is_warned_not_started(self):
        client = AdapterClient(task_registry=MagicMock())
        config = SimpleNamespace(
            discord=SimpleNamespace(enabled=True, token=None),  # no token, env empty → misconfigured
            telegram=SimpleNamespace(enabled=False),
            whatsapp=SimpleNamespace(enabled=False, phone_number_id=None, access_token=None),
        )
        with (
            patch("teleclaude.core.adapter_client._client.config", config),
            _fake_validator_env(),  # no env creds
            patch("teleclaude.core.adapter_client._client.DiscordAdapter") as discord_ctor,
            patch("teleclaude.core.adapter_client._client.RedisTransport", return_value=_make_base_adapter()),
        ):
            await client.start()

        discord_ctor.assert_not_called()  # never constructed/started
        assert "discord" not in client.adapters
        report = client.adapter_status["discord"]
        assert report.status == AdapterStatus.MISCONFIGURED
        assert report.missing == ("token",)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_configured_adapter_that_fails_to_start_does_not_crash_daemon(self):
        client = AdapterClient(task_registry=MagicMock())
        config = SimpleNamespace(
            discord=SimpleNamespace(enabled=True, token="discord-token"),
            telegram=SimpleNamespace(enabled=False),
            whatsapp=SimpleNamespace(enabled=False, phone_number_id=None, access_token=None),
        )
        start_error = "gateway 429"
        failing = _make_ui_adapter()
        failing.start = AsyncMock(side_effect=RuntimeError(start_error))
        redis_adapter = _make_base_adapter()

        with (
            patch("teleclaude.core.adapter_client._client.config", config),
            _fake_validator_env(),
            patch("teleclaude.core.adapter_client._client.DiscordAdapter", return_value=failing),
            patch("teleclaude.core.adapter_client._client.RedisTransport", return_value=redis_adapter),
        ):
            await client.start()  # must NOT raise

        assert "discord" not in client.adapters  # left unregistered (degraded)
        assert client.adapter_status["discord"].status == AdapterStatus.ERROR
        assert client.adapter_status["discord"].error == start_error
        assert client.transport is redis_adapter  # transport still came up


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
