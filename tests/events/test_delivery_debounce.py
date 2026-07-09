"""Wiring smoke test for ``_DaemonEventPlatformMixin._build_push_callbacks``.

Covers docs/project/design/architecture/notification-delivery.md: every
external delivery adapter (Telegram/Discord/WhatsApp) is registered wrapped
through ``_wrap_with_debounce`` so eligible sends coalesce through the shared
debouncer, while the API websocket push callback is registered unwrapped, and
the targeted-delivery callback is registered last for addressed recipients.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from teleclaude.config import config
from teleclaude.config.schema import CredsConfig, DiscordCreds, PersonConfig, TelegramCreds, WhatsAppCreds
from teleclaude.daemon_event_platform import _DaemonEventPlatformMixin

pytestmark = pytest.mark.functional

_DEBOUNCE_WRAPPER_FUNC_NAME = "_on_notification"
_DEBOUNCE_WRAPPER_QUALNAME_PREFIX = "_wrap_with_debounce"
_TARGETED_CALLBACK_QUALNAME_PREFIX = "build_targeted_push_callback"


def _fake_admin_person_configs() -> list[tuple[str, PersonConfig]]:
    """Build a single fake admin with credentials for all three channels."""
    person_cfg = PersonConfig(
        creds=CredsConfig(
            telegram=TelegramCreds(user_name="admin", user_id=1, chat_id="chat-1"),
            discord=DiscordCreds(user_id="discord-1"),
            whatsapp=WhatsAppCreds(phone_number="+10000000000"),
        )
    )
    return [("admin", person_cfg)]


def test_build_push_callbacks_wraps_external_adapters_and_leaves_api_push_bare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram/Discord/WhatsApp callbacks are debounce-wrapped; the API push callback is not."""
    monkeypatch.setattr(config.discord, "enabled", True)
    monkeypatch.setattr(config.whatsapp, "enabled", True)

    async def _fake_send(*_args: object, **_kwargs: object) -> str:
        return "msg-1"

    monkeypatch.setattr("teleclaude.services.telegram.send_telegram_dm", _fake_send)
    monkeypatch.setattr("teleclaude.services.discord.send_discord_dm", _fake_send)
    monkeypatch.setattr("teleclaude.services.whatsapp.send_whatsapp_message", _fake_send)

    daemon = _DaemonEventPlatformMixin()
    daemon.shutdown_event = asyncio.Event()
    daemon.client = cast("object", SimpleNamespace())

    def _notification_push(*_args: object, **_kwargs: object) -> None:
        return None

    fake_api_server = SimpleNamespace(_notification_push=_notification_push, _event_db=None)
    daemon.lifecycle = cast("object", SimpleNamespace(api_server=fake_api_server))
    daemon._event_db = None

    monkeypatch.setattr(
        _DaemonEventPlatformMixin,
        "_iter_admin_people_configs",
        lambda _self: _fake_admin_person_configs(),
    )

    push_callbacks = daemon._build_push_callbacks()

    assert len(push_callbacks) == 5

    api_callback, *external_callbacks, targeted_callback = push_callbacks
    assert api_callback is _notification_push

    assert len(external_callbacks) == 3
    for callback in external_callbacks:
        assert callback.__name__ == _DEBOUNCE_WRAPPER_FUNC_NAME
        assert callback.__qualname__.startswith(_DEBOUNCE_WRAPPER_QUALNAME_PREFIX)
        assert callback is not _notification_push

    assert targeted_callback.__name__ == _DEBOUNCE_WRAPPER_FUNC_NAME
    assert targeted_callback.__qualname__.startswith(_TARGETED_CALLBACK_QUALNAME_PREFIX)
