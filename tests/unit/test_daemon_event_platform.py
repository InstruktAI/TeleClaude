"""Characterization tests for teleclaude.daemon_event_platform."""

from __future__ import annotations

import asyncio
import logging as _logging
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

import teleclaude.daemon_event_platform as daemon_event_platform
from teleclaude.config import config as _config


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


@dataclass
class _CapturedReliabilityArgs:
    idle_threshold_ms: int | None = None
    max_attempts: int | None = None
    sweep_interval_ms: int | None = None
    dlq_destination: str | None = None


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
async def test_start_event_processor_passes_reliability_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _CapturedReliabilityArgs()

    class FakeEventProcessor:
        def __init__(
            self,
            *,
            redis_client: object,
            pipeline: object,
            consumer_name: str,
            idle_threshold_ms: int,
            max_attempts: int,
            sweep_interval_ms: int,
            dlq_destination: str,
        ) -> None:
            del redis_client, pipeline, consumer_name
            captured.idle_threshold_ms = idle_threshold_ms
            captured.max_attempts = max_attempts
            captured.sweep_interval_ms = sweep_interval_ms
            captured.dlq_destination = dlq_destination

        async def start(self, _shutdown_event: asyncio.Event) -> None:
            return None

    daemon_instance = _MinimalDaemon()
    daemon_instance.shutdown_event = asyncio.Event()  # type: ignore[assignment]
    daemon_instance.shutdown_event.set()  # type: ignore[attr-defined]
    monkeypatch.setattr(daemon_event_platform, "EventProcessor", FakeEventProcessor)

    reliability = _config.event_reliability
    original_values = (
        reliability.idle_threshold_ms,
        reliability.max_attempts,
        reliability.sweep_interval_ms,
        reliability.dlq_destination,
    )
    reliability.idle_threshold_ms = 11_000
    reliability.max_attempts = 6
    reliability.sweep_interval_ms = 1_500
    reliability.dlq_destination = "test:dlq"
    try:
        daemon_instance._start_event_processor(redis_client=object(), pipeline=object())  # type: ignore[arg-type]
        await daemon_instance._event_processor_task  # type: ignore[attr-defined]
    finally:
        (
            reliability.idle_threshold_ms,
            reliability.max_attempts,
            reliability.sweep_interval_ms,
            reliability.dlq_destination,
        ) = original_values

    assert captured.idle_threshold_ms == 11_000
    assert captured.max_attempts == 6
    assert captured.sweep_interval_ms == 1_500
    assert captured.dlq_destination == "test:dlq"


@pytest.mark.asyncio
async def test_start_internal_event_bus_configures_singleton_with_daemon_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = object()
    daemon_instance = _MinimalDaemon()
    daemon_instance.shutdown_event = asyncio.Event()  # type: ignore[assignment]
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
    await daemon_instance._internal_event_bus_task  # type: ignore[attr-defined]

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

    Whether observability is surfaced through a raised exception, a status
    attribute, a logging boundary, or another mechanism is an implementation
    choice. The spec pins only the criterion's literal contract: silent
    healthy-continuation is forbidden when Redis is configured but unreachable.
    """

    @pytest.mark.asyncio
    async def test_configured_but_unreachable_redis_surfaces_classified_failure_and_observable_state(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Both startup paths (raise and no-raise) must expose the
        criterion's two named observable surfaces — reachability transitions
        and pending recovery progress. Classified exception is additional
        evidence on the raise path, not the whole contract.
        """
        caplog.set_level(_logging.INFO, logger="teleclaude.daemon_event_platform")
        config = _config

        class _UnreachableRedisDaemon(_MinimalDaemon):
            async def _init_event_db_storage(self) -> None:
                return None

            async def _get_event_redis_client(self) -> object | None:
                return None

        daemon_instance = _UnreachableRedisDaemon()
        daemon_instance.shutdown_event = SimpleNamespace(is_set=lambda: True)  # type: ignore[assignment]

        original_url = config.redis.url
        config.redis.url = "redis://configured.example:6379"
        try:
            raised: BaseException | None = None
            try:
                await daemon_instance._start_event_platform()
            except Exception as exc:
                raised = exc

            # Build the OBSERVABLE SURFACE only from non-exception evidence:
            # daemon instance state and structured log records. Exception
            # text alone — e.g. ``RuntimeError("redis pending")`` — must
            # NOT satisfy the reachability/recovery contract. The classified
            # exception is checked separately as additional evidence on the
            # raise path.
            attr_text = " ".join(
                set(daemon_instance.__dict__) | {name for name in dir(daemon_instance) if not name.startswith("_")}
            )
            value_text = " ".join(str(v) for v in daemon_instance.__dict__.values())
            log_text_parts: list[str] = []
            for record in caplog.records:
                log_text_parts.append(record.getMessage())
                for k, v in record.__dict__.items():
                    if k.startswith("_"):
                        continue
                    log_text_parts.append(f"{k} {v}")
            log_text = " ".join(log_text_parts)

            non_exception_surface = (attr_text + " " + value_text + " " + log_text).lower()

            if raised is not None:
                # Classified failure is REQUIRED on the raise path. An
                # unrelated crash does not satisfy. (This is in ADDITION to
                # the non-exception observable surfaces below.)
                criterion_terms = ("redis", "unreachable", "connection", "event", "stream")
                assert any(t in (str(raised) + " " + type(raised).__name__).lower() for t in criterion_terms), (
                    "classified failure required on the raise path: raised "
                    f"exception must mention one of {criterion_terms!r}; got {raised!r}"
                )

            # BOTH paths must expose the criterion's two named observable
            # surfaces through state/logs/signals — exception text does NOT
            # count toward this surface.
            for concept, synonyms in (
                ("reachability transitions", ("reach", "connect", "redis", "available")),
                ("pending recovery progress", ("pending", "recover", "progress", "stale")),
            ):
                assert any(s in non_exception_surface for s in synonyms), (
                    f"criterion-named surface {concept!r} must be observable "
                    f"through daemon state, structured logs, or emitted signals "
                    f"(one of {synonyms!r}); exception text alone does not count. "
                    f"Non-exception surface was {non_exception_surface!r}"
                )
        finally:
            config.redis.url = original_url
