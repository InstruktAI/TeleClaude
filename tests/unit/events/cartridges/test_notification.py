"""Characterization tests for teleclaude.events.cartridges.notification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(
    event_type: str = "test.event",
    payload: dict[str, object] | None = None,  # guard: loose-dict
    description: str = "",
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=payload or {},
        description=description,
    )


def _make_db(
    upsert_result: tuple[int, bool] = (1, True),
    find_result: dict[str, object] | None = None,  # guard: loose-dict
) -> MagicMock:
    db = MagicMock()
    db.upsert_by_idempotency_key = AsyncMock(return_value=upsert_result)
    db.find_by_group_key = AsyncMock(return_value=find_result)
    db.update_notification_fields = AsyncMock()
    db.resolve_notification = AsyncMock()
    db.update_agent_status = AsyncMock()
    return db


def _make_context(
    schema: EventSchema | None = None,
    db: MagicMock | None = None,
    push_callbacks: list[object] | None = None,
) -> MagicMock:
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = schema
    ctx = MagicMock()
    ctx.catalog = catalog
    ctx.db = db or _make_db()
    ctx.push_callbacks = push_callbacks or []
    return ctx


def _make_schema(
    lifecycle: NotificationLifecycle | None = None,
) -> EventSchema:
    return EventSchema(
        event_type="test.event",
        description="test",
        default_level=EventLevel.OPERATIONAL,
        domain="test",
        lifecycle=lifecycle,
    )


@pytest.mark.asyncio
async def test_signal_only_classification_skips_notification():
    """Events classified as signal-only bypass all notification logic."""
    schema = _make_schema(lifecycle=NotificationLifecycle(creates=True))
    cartridge = NotificationProjectorCartridge()
    event = _make_event(payload={"_classification": {"treatment": "signal-only"}})
    db = _make_db()
    ctx = _make_context(schema=schema, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.upsert_by_idempotency_key.assert_not_called()
    db.find_by_group_key.assert_not_called()


@pytest.mark.asyncio
async def test_no_schema_passes_through():
    """Events with no schema pass through without DB interaction."""
    cartridge = NotificationProjectorCartridge()
    event = _make_event("unknown.event")
    db = _make_db()
    ctx = _make_context(schema=None, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.upsert_by_idempotency_key.assert_not_called()


@pytest.mark.asyncio
async def test_schema_without_lifecycle_passes_through():
    """Schema with no lifecycle means no notification action."""
    schema = _make_schema(lifecycle=None)
    cartridge = NotificationProjectorCartridge()
    event = _make_event()
    db = _make_db()
    ctx = _make_context(schema=schema, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.upsert_by_idempotency_key.assert_not_called()


@pytest.mark.asyncio
async def test_creates_only_lifecycle_upserts():
    """Lifecycle with creates=True triggers upsert."""
    lifecycle = NotificationLifecycle(creates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event()
    db = _make_db(upsert_result=(1, True))
    ctx = _make_context(schema=schema, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.upsert_by_idempotency_key.assert_called_once()


@pytest.mark.asyncio
async def test_resolves_lifecycle_resolves_existing_notification():
    """Lifecycle with resolves=True and group_key resolves matching notification."""
    lifecycle = NotificationLifecycle(resolves=True, group_key="slug")
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event(payload={"slug": "my-todo"})
    existing = {"id": 42}
    db = _make_db(find_result=existing)
    ctx = _make_context(schema=schema, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.resolve_notification.assert_called_once_with(42, event.payload)


@pytest.mark.asyncio
async def test_updates_lifecycle_with_existing_record_updates_fields():
    """Lifecycle with updates=True updates notification fields when existing record found."""
    lifecycle = NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["status"])
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event(payload={"slug": "my-todo", "status": "active"})
    existing = {"id": 7}
    db = _make_db(find_result=existing)
    ctx = _make_context(schema=schema, db=db)

    result = await cartridge.process(event, ctx)

    assert result is event
    db.update_notification_fields.assert_called_once()


@pytest.mark.asyncio
async def test_push_callback_invoked_after_create():
    """Push callback is called after successful notification creation."""
    lifecycle = NotificationLifecycle(creates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event()
    db = _make_db(upsert_result=(1, True))
    callback = MagicMock(return_value=None)
    ctx = _make_context(schema=schema, db=db, push_callbacks=[callback])

    await cartridge.process(event, ctx)

    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == 1  # notification_id
    assert args[3] is True  # was_created


@pytest.mark.asyncio
async def test_push_callback_exception_does_not_propagate():
    """Push callback errors are swallowed — event is still returned."""
    lifecycle = NotificationLifecycle(creates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event()
    db = _make_db(upsert_result=(1, True))
    callback = MagicMock(side_effect=RuntimeError("cb failure"))
    ctx = _make_context(schema=schema, db=db, push_callbacks=[callback])

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_creates_and_updates_with_group_key_updates_when_existing():
    """Lifecycle with both creates+updates+group_key updates (not upserts) when record already exists."""
    lifecycle = NotificationLifecycle(creates=True, updates=True, group_key="slug", meaningful_fields=["phase"])
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = NotificationProjectorCartridge()
    event = _make_event(payload={"slug": "x", "phase": "build"})
    existing = {"id": 3}
    db = _make_db(find_result=existing)
    ctx = _make_context(schema=schema, db=db)

    await cartridge.process(event, ctx)

    db.update_notification_fields.assert_called_once()
    db.upsert_by_idempotency_key.assert_not_called()
