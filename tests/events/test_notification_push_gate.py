"""Push notification gate — actionability, never level, decides interruption.

Covers docs/project/design/architecture/notification-delivery.md: the
notification-projector cartridge forwards the schema's ``actionable`` flag to
push callbacks, and every push surface (DM adapters, WebSocket) applies the
same ``actionable and (was_created or is_meaningful)`` gate.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from teleclaude.api_server import APIServer
from teleclaude.core.models import JsonDict
from teleclaude.events import build_default_catalog
from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.db import EventDB
from teleclaude.events.delivery.discord import DiscordDeliveryAdapter
from teleclaude.events.delivery.telegram import TelegramDeliveryAdapter
from teleclaude.events.delivery.whatsapp import WhatsAppDeliveryAdapter
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

if TYPE_CHECKING:
    from fastapi import WebSocket

    from teleclaude.core.adapter_client import AdapterClient

pytestmark = pytest.mark.functional

_ACTIONABLE_EVENT_TYPE = "system.worker.crashed"
_ROUTINE_EVENT_TYPE = "system.process.reaped"

_DELIVERY_ADAPTERS: list[
    tuple[type[TelegramDeliveryAdapter] | type[DiscordDeliveryAdapter] | type[WhatsAppDeliveryAdapter], str]
] = [
    (TelegramDeliveryAdapter, "chat_id"),
    (DiscordDeliveryAdapter, "user_id"),
    (WhatsAppDeliveryAdapter, "phone_number"),
]


def _event(event_type: str) -> EventEnvelope:
    """Build a minimal envelope for a registered event type."""
    schema = build_default_catalog().get(event_type)
    assert schema is not None
    return EventEnvelope(
        event=schema.event_type,
        source="test",
        level=schema.default_level,
        domain=schema.domain,
        visibility=schema.default_visibility,
        payload={},
    )


@pytest.mark.asyncio
async def test_projector_forwards_actionable_true_for_actionable_schema(tmp_path: Path) -> None:
    """An actionable=True schema forwards actionable=True to push callbacks."""
    catalog = build_default_catalog()
    schema = catalog.get(_ACTIONABLE_EVENT_TYPE)
    assert schema is not None
    assert schema.actionable is True

    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    captured: list[bool] = []
    try:
        context = PipelineContext(catalog=catalog, db=db)
        context.push_callbacks.append(lambda *args: captured.append(args[5]))
        projector = NotificationProjectorCartridge()
        await projector.process(_event(_ACTIONABLE_EVENT_TYPE), context)
    finally:
        await db.close()

    assert captured == [True]


@pytest.mark.asyncio
async def test_projector_forwards_actionable_false_for_routine_schema(tmp_path: Path) -> None:
    """A routine (actionable=False) schema forwards actionable=False to push callbacks."""
    catalog = build_default_catalog()
    schema = catalog.get(_ROUTINE_EVENT_TYPE)
    assert schema is not None
    assert schema.actionable is False

    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    captured: list[bool] = []
    try:
        context = PipelineContext(catalog=catalog, db=db)
        context.push_callbacks.append(lambda *args: captured.append(args[5]))
        projector = NotificationProjectorCartridge()
        await projector.process(_event(_ROUTINE_EVENT_TYPE), context)
    finally:
        await db.close()

    assert captured == [False]


class _StubSend:
    """Records whether the adapter's send function was invoked."""

    def __init__(self) -> None:
        self.invoked = False

    async def __call__(self, **_kwargs: object) -> str:
        """Record invocation and return a fake message id."""
        self.invoked = True
        return "msg-1"


@pytest.mark.parametrize("adapter_cls,recipient_kwarg", _DELIVERY_ADAPTERS)
@pytest.mark.asyncio
async def test_delivery_adapter_pushes_on_created_actionable_event(
    adapter_cls: type[TelegramDeliveryAdapter] | type[DiscordDeliveryAdapter] | type[WhatsAppDeliveryAdapter],
    recipient_kwarg: str,
) -> None:
    """actionable=True, was_created=True pushes to the delivery surface."""
    stub_send = _StubSend()
    adapter = adapter_cls(**{recipient_kwarg: "target", "send_fn": stub_send})

    await adapter.on_notification(1, _ACTIONABLE_EVENT_TYPE, 0, True, False, True)

    assert stub_send.invoked is True


@pytest.mark.parametrize("adapter_cls,recipient_kwarg", _DELIVERY_ADAPTERS)
@pytest.mark.asyncio
async def test_delivery_adapter_pushes_on_meaningful_update_when_actionable(
    adapter_cls: type[TelegramDeliveryAdapter] | type[DiscordDeliveryAdapter] | type[WhatsAppDeliveryAdapter],
    recipient_kwarg: str,
) -> None:
    """actionable=True, was_created=False, is_meaningful=True still pushes (was_created OR is_meaningful)."""
    stub_send = _StubSend()
    adapter = adapter_cls(**{recipient_kwarg: "target", "send_fn": stub_send})

    await adapter.on_notification(1, "system.entity.degraded", 0, False, True, True)

    assert stub_send.invoked is True


@pytest.mark.parametrize("adapter_cls,recipient_kwarg", _DELIVERY_ADAPTERS)
@pytest.mark.asyncio
async def test_delivery_adapter_suppresses_non_actionable_event(
    adapter_cls: type[TelegramDeliveryAdapter] | type[DiscordDeliveryAdapter] | type[WhatsAppDeliveryAdapter],
    recipient_kwarg: str,
) -> None:
    """actionable=False never pushes, regardless of was_created/is_meaningful."""
    stub_send = _StubSend()
    adapter = adapter_cls(**{recipient_kwarg: "target", "send_fn": stub_send})

    await adapter.on_notification(1, _ROUTINE_EVENT_TYPE, 0, True, True, False)

    assert stub_send.invoked is False


@pytest.mark.parametrize("adapter_cls,recipient_kwarg", _DELIVERY_ADAPTERS)
@pytest.mark.asyncio
async def test_delivery_adapter_suppresses_actionable_event_without_meaningful_content(
    adapter_cls: type[TelegramDeliveryAdapter] | type[DiscordDeliveryAdapter] | type[WhatsAppDeliveryAdapter],
    recipient_kwarg: str,
) -> None:
    """actionable=True but neither created nor meaningful never pushes."""
    stub_send = _StubSend()
    adapter = adapter_cls(**{recipient_kwarg: "target", "send_fn": stub_send})

    await adapter.on_notification(1, "system.entity.degraded", 0, False, False, True)

    assert stub_send.invoked is False


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
async def test_ws_push_broadcasts_on_created_actionable_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """actionable=True, was_created=True, is_meaningful=False still broadcasts (pins the created-only path)."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        notification_id = await db.insert_notification(_event(_ACTIONABLE_EVENT_TYPE))
        server = await _server_with_subscribed_client(db)
        broadcasts: list[tuple[str, JsonDict]] = []
        monkeypatch.setattr(
            server, "_broadcast_payload", lambda event, payload, **_kw: broadcasts.append((event, payload))
        )

        await server._notification_push(notification_id, _ACTIONABLE_EVENT_TYPE, 0, True, False, True)
    finally:
        await db.close()

    assert len(broadcasts) == 1


@pytest.mark.asyncio
async def test_ws_push_broadcasts_on_meaningful_update_when_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """actionable=True, was_created=False, is_meaningful=True broadcasts."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        notification_id = await db.insert_notification(_event("system.entity.degraded"))
        server = await _server_with_subscribed_client(db)
        broadcasts: list[tuple[str, JsonDict]] = []
        monkeypatch.setattr(
            server, "_broadcast_payload", lambda event, payload, **_kw: broadcasts.append((event, payload))
        )

        await server._notification_push(notification_id, "system.entity.degraded", 0, False, True, True)
    finally:
        await db.close()

    assert len(broadcasts) == 1


@pytest.mark.asyncio
async def test_ws_push_suppresses_non_actionable_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """actionable=False never broadcasts, regardless of was_created/is_meaningful."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        notification_id = await db.insert_notification(_event(_ROUTINE_EVENT_TYPE))
        server = await _server_with_subscribed_client(db)
        broadcasts: list[tuple[str, JsonDict]] = []
        monkeypatch.setattr(
            server, "_broadcast_payload", lambda event, payload, **_kw: broadcasts.append((event, payload))
        )

        await server._notification_push(notification_id, _ROUTINE_EVENT_TYPE, 0, True, True, False)
    finally:
        await db.close()

    assert broadcasts == []


@pytest.mark.asyncio
async def test_ws_push_suppresses_actionable_event_without_meaningful_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """actionable=True but neither created nor meaningful never broadcasts."""
    db = EventDB(tmp_path / "events.sqlite")
    await db.initialize()
    try:
        notification_id = await db.insert_notification(_event("system.entity.degraded"))
        server = await _server_with_subscribed_client(db)
        broadcasts: list[tuple[str, JsonDict]] = []
        monkeypatch.setattr(
            server, "_broadcast_payload", lambda event, payload, **_kw: broadcasts.append((event, payload))
        )

        await server._notification_push(notification_id, "system.entity.degraded", 0, False, False, True)
    finally:
        await db.close()

    assert broadcasts == []
