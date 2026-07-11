"""Recipient-aware notification delivery.

Covers `project/design/architecture/notification-delivery` § addressed-vs-
broadcast: an actionable notification addressed to a principal is persisted
with its recipient, delivered only to that principal's resolved channel, and
excluded from every broadcast surface (the admin DM adapters, the WebSocket
push, and the global notification list). An unresolvable recipient withholds
the push rather than falling back to the admin fan-out.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

import teleclaude.core.person_messaging as person_messaging_mod
import teleclaude.events.delivery.targeted as targeted_mod
from teleclaude.api_server import APIServer
from teleclaude.config.schema import (
    CredsConfig,
    DiscordCreds,
    GlobalConfig,
    PersonConfig,
    PersonEntry,
    TelegramCreds,
)
from teleclaude.core.models import JsonDict
from teleclaude.daemon_event_platform import _DeliveryAdapter, _wrap_with_debounce
from teleclaude.events import build_default_catalog
from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.db import EventDB
from teleclaude.events.delivery.debounce import DeliveryChannel, DeliveryDebouncer
from teleclaude.events.delivery.targeted import build_targeted_push_callback
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

if TYPE_CHECKING:
    from fastapi import WebSocket

    from teleclaude.core.adapter_client import AdapterClient

pytestmark = pytest.mark.functional

_ACTIONABLE_EVENT_TYPE = "notification.escalation"
_NOTIFICATION_ID = 42
_GROUP_IDENTITY = "group-1"

_TELEGRAM_SLUG = "operator-tg"
_TELEGRAM_CHAT_ID = "chat-999"
_DISCORD_SLUG = "operator-discord"
_DISCORD_USER_ID = "discord-999"
_EMAIL_SLUG = "operator-email"
_EMAIL_ADDRESS = "operator@example.com"
_UNKNOWN_SLUG = "ghost"

_ADMIN_CHAT_ID = "admin-chat"


def _event(event_type: str, payload: JsonDict) -> EventEnvelope:
    """Build an envelope for a registered event type carrying the given payload."""
    schema = build_default_catalog().get(event_type)
    assert schema is not None
    return EventEnvelope(
        event=schema.event_type,
        source="test",
        level=schema.default_level,
        domain=schema.domain,
        visibility=schema.default_visibility,
        payload=payload,
    )


def _install_people(monkeypatch: pytest.MonkeyPatch, people: dict[str, tuple[PersonEntry, PersonConfig]]) -> None:
    """Wire ``person_messaging``'s config loaders to a fixed in-memory people set."""
    entries = [entry for entry, _ in people.values()]
    configs_by_slug = {slug: cfg for slug, (_, cfg) in people.items()}

    monkeypatch.setattr(person_messaging_mod, "load_global_config", lambda: GlobalConfig(people=entries))
    monkeypatch.setattr(
        person_messaging_mod,
        "load_person_config_for_entry",
        lambda person, _people_dir: configs_by_slug[person.slug],
    )


class _CapturingDebouncer:
    """Records ``schedule`` calls instead of running a real timer."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []  # guard: loose-dict - captures schedule()'s **kwargs verbatim

    def schedule(self, **kwargs: object) -> None:
        """Record the call instead of scheduling a real timer."""
        self.calls.append(kwargs)


class _StubAdapter:
    """A `_DeliveryAdapter` double that records whether it was invoked."""

    def __init__(self) -> None:
        self.invoked = False

    def recipient(self) -> str:
        """Return the fixed admin chat id this stub represents."""
        return _ADMIN_CHAT_ID

    async def on_notification(
        self,
        _notification_id: int,
        _event_type: str,
        _level: int,
        _was_created: bool,
        _is_meaningful: bool,
        _actionable: bool,
    ) -> None:
        """Record that the admin adapter was invoked."""
        self.invoked = True


# --- Task 1: persistence -----------------------------------------------------


@pytest.mark.asyncio
async def test_addressed_event_persists_recipient_on_row(tmp_path: Path) -> None:
    """An addressed actionable notification persists its recipient on the row (SC-3)."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        catalog = build_default_catalog()
        context = PipelineContext(catalog=catalog, db=db)
        projector = NotificationProjectorCartridge()

        await projector.process(
            _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-addressed", "recipient": _TELEGRAM_SLUG}),
            context,
        )

        row = await db.find_by_group_key("escalation_id", "esc-addressed")
        assert row is not None
        assert row["recipient"] == _TELEGRAM_SLUG
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unaddressed_event_persists_null_recipient(tmp_path: Path) -> None:
    """An unaddressed actionable notification persists a null recipient (SC-2, SC-6)."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        catalog = build_default_catalog()
        context = PipelineContext(catalog=catalog, db=db)
        projector = NotificationProjectorCartridge()

        await projector.process(
            _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-broadcast"}),
            context,
        )

        row = await db.find_by_group_key("escalation_id", "esc-broadcast")
        assert row is not None
        assert row["recipient"] is None
    finally:
        await db.close()


# --- Task 4: broadcast-surface exclusion -------------------------------------


@pytest.mark.asyncio
async def test_list_notifications_excludes_addressed_row(tmp_path: Path) -> None:
    """The global notification list omits a row carrying a recipient (SC-1)."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        addressed = _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-a"})
        broadcast = _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-b"})
        await db.insert_notification(addressed, recipient=_TELEGRAM_SLUG)
        broadcast_id = await db.insert_notification(broadcast, recipient=None)

        rows = await db.list_notifications()

        ids = [row["id"] for row in rows]
        assert broadcast_id in ids
        assert all(row["recipient"] is None for row in rows)
    finally:
        await db.close()


async def _server_with_subscribed_client(db: EventDB) -> APIServer:
    """Build a real APIServer wired to the given EventDB with one subscribed WS client."""
    stub_client = cast(
        "AdapterClient",
        SimpleNamespace(adapters={}, send_message=None, start=None, stop=None),
    )
    server = APIServer(client=stub_client, cache=None)
    server._event_db = db
    fake_ws = cast("WebSocket", object())
    server._client_subscriptions[fake_ws] = {"local": {"notifications"}}
    return server


@pytest.mark.asyncio
async def test_notification_push_skips_addressed_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The WebSocket push does not broadcast a row carrying a recipient (SC-1)."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        envelope = _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-ws"})
        notification_id = await db.insert_notification(envelope, recipient=_TELEGRAM_SLUG)
        server = await _server_with_subscribed_client(db)
        broadcasts: list[tuple[str, JsonDict]] = []
        monkeypatch.setattr(
            server, "_broadcast_payload", lambda event, payload, **_kw: broadcasts.append((event, payload))
        )

        await server._notification_push(
            notification_id, _ACTIONABLE_EVENT_TYPE, 0, True, False, True, recipient=_TELEGRAM_SLUG
        )
    finally:
        await db.close()

    assert broadcasts == []


# --- Task 3: admin fan-out is bypassed for an addressed notification ---------


@pytest.mark.asyncio
async def test_admin_wrapper_skips_when_notification_is_addressed() -> None:
    """A pre-registered admin adapter never fires for an addressed change (SC-1)."""
    debouncer = DeliveryDebouncer()
    adapter = _StubAdapter()
    wrapped = _wrap_with_debounce(debouncer, DeliveryChannel.TELEGRAM, cast("_DeliveryAdapter", adapter))

    await wrapped(_NOTIFICATION_ID, _ACTIONABLE_EVENT_TYPE, 0, True, False, True, _GROUP_IDENTITY, 0.0, _TELEGRAM_SLUG)

    assert adapter.invoked is False


# --- Task 3: targeted delivery routes to the resolved channel ----------------


@pytest.mark.asyncio
async def test_targeted_dm_delivery_schedules_through_debouncer_to_recipient_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An addressed Telegram-preferring recipient schedules through the debouncer to their chat id (SC-1, SC-4)."""
    person_config = PersonConfig(
        preferred_channel=targeted_mod.MessagingChannel.TELEGRAM,
        creds=CredsConfig(telegram=TelegramCreds(user_name="tg", user_id=1, chat_id=_TELEGRAM_CHAT_ID)),
    )
    _install_people(
        monkeypatch,
        {_TELEGRAM_SLUG: (PersonEntry(name="TG", email="tg@example.com", slug=_TELEGRAM_SLUG), person_config)},
    )
    sent: list[tuple[str, str]] = []

    async def _fake_telegram(chat_id: str, content: str, *_args: object, **_kwargs: object) -> str:
        sent.append((chat_id, content))
        return "msg-1"

    monkeypatch.setattr(targeted_mod, "send_telegram_dm", _fake_telegram)
    debouncer = _CapturingDebouncer()
    callback = build_targeted_push_callback(cast("DeliveryDebouncer", debouncer))

    await callback(_NOTIFICATION_ID, _ACTIONABLE_EVENT_TYPE, 0, True, False, True, _GROUP_IDENTITY, 5.0, _TELEGRAM_SLUG)

    assert len(debouncer.calls) == 1
    call = debouncer.calls[0]
    assert call["channel"] is DeliveryChannel.TELEGRAM
    assert call["recipient"] == _TELEGRAM_CHAT_ID
    assert call["debounce_s"] == 5.0

    runner = cast("Callable[[], Awaitable[None]]", call["runner"])
    await runner()

    assert sent == [(_TELEGRAM_CHAT_ID, f"[{_ACTIONABLE_EVENT_TYPE}] Notification #{_NOTIFICATION_ID} created.")]


@pytest.mark.asyncio
async def test_targeted_delivery_resolves_to_persons_preferred_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """An addressed recipient whose preferred channel is Discord (not the Telegram default) resolves to Discord (SC-4)."""
    person_config = PersonConfig(
        preferred_channel=targeted_mod.MessagingChannel.DISCORD,
        creds=CredsConfig(discord=DiscordCreds(user_id=_DISCORD_USER_ID)),
    )
    _install_people(
        monkeypatch,
        {_DISCORD_SLUG: (PersonEntry(name="Disc", email="disc@example.com", slug=_DISCORD_SLUG), person_config)},
    )
    debouncer = _CapturingDebouncer()
    callback = build_targeted_push_callback(cast("DeliveryDebouncer", debouncer))

    await callback(_NOTIFICATION_ID, _ACTIONABLE_EVENT_TYPE, 0, True, False, True, _GROUP_IDENTITY, 5.0, _DISCORD_SLUG)

    assert len(debouncer.calls) == 1
    assert debouncer.calls[0]["channel"] is DeliveryChannel.DISCORD
    assert debouncer.calls[0]["recipient"] == _DISCORD_USER_ID


@pytest.mark.asyncio
async def test_targeted_email_delivery_is_immediate_and_bypasses_debouncer(monkeypatch: pytest.MonkeyPatch) -> None:
    """An addressed email-preferring recipient sends immediately, without touching the debouncer (SC-4)."""
    person_config = PersonConfig(preferred_channel=targeted_mod.MessagingChannel.EMAIL)
    _install_people(
        monkeypatch,
        {_EMAIL_SLUG: (PersonEntry(name="Mail", email=_EMAIL_ADDRESS, slug=_EMAIL_SLUG), person_config)},
    )
    sent: list[tuple[str, str]] = []

    async def _fake_email(to: str, subject: str, *_args: object, **_kwargs: object) -> None:
        sent.append((to, subject))

    monkeypatch.setattr(targeted_mod, "send_email", _fake_email)
    debouncer = _CapturingDebouncer()
    callback = build_targeted_push_callback(cast("DeliveryDebouncer", debouncer))

    await callback(_NOTIFICATION_ID, _ACTIONABLE_EVENT_TYPE, 0, True, False, True, _GROUP_IDENTITY, 5.0, _EMAIL_SLUG)

    assert debouncer.calls == []
    assert len(sent) == 1
    assert sent[0][0] == _EMAIL_ADDRESS


# --- Task 5: unresolvable recipient -------------------------------------------


@pytest.mark.asyncio
async def test_unresolvable_recipient_withholds_push_but_row_persists_and_sibling_delivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unresolvable recipient withholds delivery and keeps the row; a sibling notification still delivers (SC-5)."""
    person_config = PersonConfig(
        preferred_channel=targeted_mod.MessagingChannel.TELEGRAM,
        creds=CredsConfig(telegram=TelegramCreds(user_name="tg", user_id=1, chat_id=_TELEGRAM_CHAT_ID)),
    )
    _install_people(
        monkeypatch,
        {_TELEGRAM_SLUG: (PersonEntry(name="TG", email="tg@example.com", slug=_TELEGRAM_SLUG), person_config)},
    )
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        catalog = build_default_catalog()
        context = PipelineContext(catalog=catalog, db=db)
        debouncer = _CapturingDebouncer()
        context.push_callbacks.append(build_targeted_push_callback(cast("DeliveryDebouncer", debouncer)))
        projector = NotificationProjectorCartridge()

        await projector.process(
            _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-unresolvable", "recipient": _UNKNOWN_SLUG}),
            context,
        )
        await projector.process(
            _event(_ACTIONABLE_EVENT_TYPE, {"escalation_id": "esc-sibling", "recipient": _TELEGRAM_SLUG}),
            context,
        )

        unresolvable_row = await db.find_by_group_key("escalation_id", "esc-unresolvable")
        sibling_row = await db.find_by_group_key("escalation_id", "esc-sibling")
        assert unresolvable_row is not None
        assert unresolvable_row["recipient"] == _UNKNOWN_SLUG
        assert sibling_row is not None
        assert sibling_row["recipient"] == _TELEGRAM_SLUG

        assert len(debouncer.calls) == 1
        assert debouncer.calls[0]["recipient"] == _TELEGRAM_CHAT_ID
    finally:
        await db.close()
