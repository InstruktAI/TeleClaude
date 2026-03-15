"""Characterization tests for teleclaude.events.cartridges.dedup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.dedup import DeduplicationCartridge
from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(  # guard: loose-dict
    event_type: str = "test.event", payload: dict[str, object] | None = None
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=payload or {},
    )


def _make_context(
    schema: EventSchema | None = None,
    idempotency_key: str | None = None,
    key_exists: bool = False,
) -> MagicMock:
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = schema
    catalog.build_idempotency_key.return_value = idempotency_key
    db = MagicMock()
    db.idempotency_key_exists = AsyncMock(return_value=key_exists)
    ctx = MagicMock()
    ctx.catalog = catalog
    ctx.db = db
    return ctx


def _make_schema(
    event_type: str = "test.event",
    lifecycle: NotificationLifecycle | None = None,
) -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="test schema",
        default_level=EventLevel.OPERATIONAL,
        domain="test",
        lifecycle=lifecycle,
        idempotency_fields=["id"],
    )


@pytest.mark.asyncio
async def test_unknown_event_passes_through():
    """Events with no schema pass through without dedup check."""
    cartridge = DeduplicationCartridge()
    event = _make_event("unknown.event")
    ctx = _make_context(schema=None)

    result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.idempotency_key_exists.assert_not_called()


@pytest.mark.asyncio
async def test_no_idempotency_key_passes_through():
    """Events whose schema yields no idempotency key pass through."""
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event()
    ctx = _make_context(schema=schema, idempotency_key=None)

    result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.idempotency_key_exists.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_event_dropped():
    """Event with an already-seen idempotency key is dropped (returns None)."""
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"})
    ctx = _make_context(schema=schema, idempotency_key="test.event:abc", key_exists=True)

    result = await cartridge.process(event, ctx)

    assert result is None


@pytest.mark.asyncio
async def test_new_event_passes_through_and_stamps_key():
    """First-seen event passes through with idempotency_key stamped onto envelope."""
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"})
    ctx = _make_context(schema=schema, idempotency_key="test.event:abc", key_exists=False)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.idempotency_key == "test.event:abc"


@pytest.mark.asyncio
async def test_updates_only_schema_skips_dedup():
    """Schema with updates=True, creates=False bypasses dedup even when key exists."""
    lifecycle = NotificationLifecycle(creates=False, updates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"})
    ctx = _make_context(schema=schema, idempotency_key="test.event:abc", key_exists=True)

    result = await cartridge.process(event, ctx)

    assert result is not None
    ctx.db.idempotency_key_exists.assert_not_called()


@pytest.mark.asyncio
async def test_creates_and_updates_schema_does_dedup():
    """Schema with both creates=True and updates=True does apply dedup."""
    lifecycle = NotificationLifecycle(creates=True, updates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"})
    ctx = _make_context(schema=schema, idempotency_key="test.event:abc", key_exists=True)

    result = await cartridge.process(event, ctx)

    assert result is None
