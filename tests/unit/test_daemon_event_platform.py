"""Characterization tests for teleclaude.daemon_event_platform."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

import teleclaude.daemon_event_platform as daemon_event_platform


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
