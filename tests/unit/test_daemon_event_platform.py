"""Characterization tests for teleclaude.daemon_event_platform."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import teleclaude.daemon_event_platform as daemon_event_platform
from teleclaude.config import config as _config


@pytest.mark.unit
def test_daemon_project_config_path_resolves_to_working_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    # The daemon's project config is at its working dir — NOT ~/.teleclaude (config.yml's dir),
    # which holds the GLOBAL teleclaude.yml and is not a ProjectConfig.
    monkeypatch.setattr(daemon_event_platform.config.computer, "default_working_dir", "/srv/proj")
    assert daemon_event_platform.daemon_project_config_path() == Path("/srv/proj") / "teleclaude.yml"


class _RecorderDaemon(daemon_event_platform._DaemonEventPlatformMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.lifecycle = SimpleNamespace(api_server=None)
        self._event_db = object()

    def _register_api_push_callback(self, push_callbacks: list[Callable[..., object]]) -> None:
        self.calls.append("api")
        push_callbacks.append(lambda: "api")

    def _register_telegram_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        self.calls.append("telegram")
        push_callbacks.append(lambda: "telegram")

    def _register_discord_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        self.calls.append("discord")
        push_callbacks.append(lambda: "discord")

    def _register_whatsapp_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        self.calls.append("whatsapp")
        push_callbacks.append(lambda: "whatsapp")


class _MinimalDaemon(daemon_event_platform._DaemonEventPlatformMixin):
    def __init__(self) -> None:
        self.lifecycle = SimpleNamespace(api_server=None)
        self._event_db = object()

    def _log_background_task_exception(self, _task_name: str) -> Callable[[asyncio.Task[object]], None]:
        return lambda _task: None


def _make_event_processor_redis() -> MagicMock:
    redis = MagicMock()
    redis.xgroup_create = AsyncMock()
    redis.xpending_range = AsyncMock(return_value=[])
    redis.xautoclaim = AsyncMock(return_value=(b"0-0", [], []))
    redis.xreadgroup = AsyncMock(return_value=[])
    return redis


def test_build_push_callbacks_invokes_registrars_in_fixed_order() -> None:
    daemon_instance = _RecorderDaemon()

    callbacks = daemon_instance._build_push_callbacks()

    assert daemon_instance.calls == ["api", "telegram", "discord", "whatsapp"]
    assert [callback() for callback in callbacks] == ["api", "telegram", "discord", "whatsapp"]


def test_register_api_push_callback_binds_event_db_and_notification_push() -> None:
    push_calls: list[str] = []

    def notification_push(*args: object, **kwargs: object) -> None:
        del args, kwargs
        push_calls.append("push")

    api_server = SimpleNamespace(
        _event_db=None,
        _notification_push=notification_push,
    )
    daemon_instance = _MinimalDaemon()
    daemon_instance.lifecycle = SimpleNamespace(api_server=api_server)

    callbacks: list[Callable[..., object]] = []
    daemon_instance._register_api_push_callback(callbacks)

    assert api_server._event_db is daemon_instance._event_db
    assert callbacks == [api_server._notification_push]


def test_configure_event_producer_registers_global_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
    daemon_instance = _MinimalDaemon()
    monkeypatch.setattr(
        daemon_event_platform,
        "configure_producer",
        lambda producer: registered.setdefault("producer", producer),
    )

    producer = daemon_instance._configure_event_producer(redis_client="redis-client")

    assert registered["producer"] is producer
    assert producer._redis == "redis-client"


@pytest.mark.asyncio
async def test_start_event_processor_registers_distinct_redis_groups_per_computer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def groups_for(computer_name: str) -> set[str]:
        monkeypatch.setattr(_config.computer, "name", computer_name)
        redis = _make_event_processor_redis()
        daemon_instance = _MinimalDaemon()
        daemon_instance.shutdown_event = asyncio.Event()
        daemon_instance.shutdown_event.set()

        daemon_instance._start_event_processor(redis_client=redis, pipeline=MagicMock())
        await daemon_instance._event_processor_task

        return {call_args.args[1] for call_args in redis.xgroup_create.await_args_list}

    mozmini_groups = await groups_for("MozMini")
    mozbook_groups = await groups_for("MozBook")

    assert mozmini_groups
    assert mozbook_groups
    assert mozmini_groups.isdisjoint(mozbook_groups)


@pytest.mark.asyncio
async def test_start_event_processor_passes_event_reliability_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}  # guard: loose-dict - captures EventProcessor constructor kwargs.

    class _FakeEventProcessor:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def start(self, _shutdown_event: asyncio.Event) -> None:
            return None

    monkeypatch.setattr(daemon_event_platform, "EventProcessor", _FakeEventProcessor)
    daemon_instance = _MinimalDaemon()
    daemon_instance.shutdown_event = asyncio.Event()

    daemon_instance._start_event_processor(redis_client=object(), pipeline=MagicMock())
    await daemon_instance._event_processor_task

    reliability = _config.event_reliability
    assert captured["idle_threshold_ms"] == reliability.idle_threshold_ms
    assert captured["max_attempts"] == reliability.max_attempts
    assert captured["sweep_interval_ms"] == reliability.sweep_interval_ms
    assert captured["dlq_destination"] == reliability.dlq_destination


@pytest.mark.asyncio
async def test_start_internal_event_bus_configures_singleton_with_daemon_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = object()
    daemon_instance = _MinimalDaemon()
    daemon_instance.shutdown_event = asyncio.Event()
    captured: dict[str, object] = {}  # guard: loose-dict - Test captures heterogeneous call fields.

    class _FakeBus:
        async def start(self, shutdown_event: asyncio.Event) -> None:
            captured["shutdown_event"] = shutdown_event

    def _configure_event_bus(*, role: str, redis_client: object) -> _FakeBus:
        captured["role"] = role
        captured["redis_client"] = redis_client
        return _FakeBus()

    monkeypatch.setattr(daemon_event_platform, "configure_event_bus", _configure_event_bus)

    daemon_instance._start_internal_event_bus(redis_client)
    await daemon_instance._internal_event_bus_task

    assert captured["role"] == "daemon"
    assert captured["redis_client"] is redis_client
    assert captured["shutdown_event"] is daemon_instance.shutdown_event


# ---------------------------------------------------------------------------
# Specs (xfail) for guaranteed-event-consumption
# These pin the post-implementation contract; remove pytestmark when satisfied.
# ---------------------------------------------------------------------------


class TestStartupRedisAvailabilitySpecs:
    """Configured-but-unreachable Redis must not silently enter a
    healthy-but-no-Streams state.

    Verbatim requirement criterion (from `requirements.md`):

    > **Startup Redis availability.** When Redis is configured for the event
    > platform but unreachable at daemon startup, the daemon does not silently
    > enter a healthy-but-no-Streams state. Startup and recovery state,
    > including reachability transitions and pending recovery progress, are
    > observable.

    The spec pins the criterion through startup failure. Logs are diagnostic
    and are not assertion targets.
    """

    @pytest.mark.asyncio
    async def test_configured_but_unreachable_redis_does_not_start_event_platform(self) -> None:
        config = _config

        class _UnreachableRedisDaemon(_MinimalDaemon):
            async def _init_event_db_storage(self) -> None:
                return None

            async def _get_event_redis_client(self) -> object | None:
                return None

        daemon_instance = _UnreachableRedisDaemon()
        daemon_instance.shutdown_event = SimpleNamespace(is_set=lambda: True)

        original_url = config.redis.url
        config.redis.url = "redis://configured.example:6379"
        try:
            with pytest.raises(RuntimeError):
                await daemon_instance._start_event_platform()
        finally:
            config.redis.url = original_url
