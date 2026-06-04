"""Characterization tests for teleclaude.events.cartridges.dedup."""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.dedup import DeduplicationCartridge
from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle, build_default_catalog
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(  # guard: loose-dict
    event_type: str = "test.event",
    payload: Mapping[str, object] | None = None,
    event_id: str | None = None,
) -> EventEnvelope:
    resolved_payload = dict(payload or {})
    if event_id is None:
        return EventEnvelope(
            event=event_type,
            source="test",
            level=EventLevel.OPERATIONAL,
            domain="test",
            visibility=EventVisibility.LOCAL,
            payload=resolved_payload,
        )
    return EventEnvelope(
        event=event_type,
        event_id=event_id,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=resolved_payload,
    )


def _make_context(
    schema: EventSchema | None = None,
    key_exists: bool = False,
) -> MagicMock:
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = schema
    db = MagicMock()
    db.idempotency_key_exists = AsyncMock(return_value=key_exists)
    ctx = MagicMock()
    ctx.catalog = catalog
    ctx.db = db
    return ctx


def _make_real_context(catalog: EventCatalog, key_exists: AsyncMock) -> MagicMock:
    db = MagicMock()
    db.idempotency_key_exists = key_exists
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
async def test_schema_event_checks_event_identity() -> None:
    """Known events use the envelope event_id as their deduplication key."""
    event_id = "33333333-3333-4333-8333-333333333333"
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(event_id=event_id)
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.idempotency_key == event_id
    ctx.db.idempotency_key_exists.assert_called_once_with(event_id)


@pytest.mark.asyncio
async def test_duplicate_event_dropped():
    """Event with an already-seen event identity is dropped."""
    event_id = "44444444-4444-4444-8444-444444444444"
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"}, event_id=event_id)
    ctx = _make_context(schema=schema, key_exists=True)

    result = await cartridge.process(event, ctx)

    assert result is None


@pytest.mark.asyncio
async def test_fresh_todo_creation_with_seen_slug_is_not_dropped() -> None:
    """Fresh todo-created emits for an existing subject must keep their own event identity."""
    event_type = "domain.software-development.planning.todo_created"
    old_subject_key = f"{event_type}:notification-dispatch-service"
    fresh_event_id = "11111111-1111-4111-8111-111111111111"

    async def _key_exists(key: str) -> bool:
        return key == old_subject_key

    cartridge = DeduplicationCartridge()
    event = _make_event(
        event_type=event_type,
        payload={"slug": "notification-dispatch-service", "kind": "todo"},
        event_id=fresh_event_id,
    )
    ctx = _make_real_context(build_default_catalog(), AsyncMock(side_effect=_key_exists))

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.idempotency_key == fresh_event_id


@pytest.mark.asyncio
async def test_replayed_event_with_seen_event_id_is_dropped() -> None:
    """Replay delivery of the same event identity is the duplicate path."""
    event_type = "domain.software-development.planning.todo_created"
    event_id = "22222222-2222-4222-8222-222222222222"

    async def _key_exists(key: str) -> bool:
        return key == event_id

    cartridge = DeduplicationCartridge()
    event = _make_event(
        event_type=event_type,
        payload={"slug": "notification-dispatch-service", "kind": "todo"},
        event_id=event_id,
    )
    ctx = _make_real_context(build_default_catalog(), AsyncMock(side_effect=_key_exists))

    result = await cartridge.process(event, ctx)

    assert result is None


@pytest.mark.asyncio
async def test_new_event_passes_through_and_stamps_key():
    """First-seen event passes through with idempotency_key stamped onto envelope."""
    event_id = "55555555-5555-4555-8555-555555555555"
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"}, event_id=event_id)
    ctx = _make_context(schema=schema, key_exists=False)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.idempotency_key == event_id


@pytest.mark.asyncio
async def test_updates_only_schema_skips_dedup():
    """Schema with updates=True, creates=False bypasses dedup even when key exists."""
    lifecycle = NotificationLifecycle(creates=False, updates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = DeduplicationCartridge()
    event = _make_event(payload={"id": "abc"})
    ctx = _make_context(schema=schema, key_exists=True)

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
    ctx = _make_context(schema=schema, key_exists=True)

    result = await cartridge.process(event, ctx)

    assert result is None


@pytest.mark.asyncio
async def test_payload_subject_fields_do_not_feed_dedup_key() -> None:
    """Subject payload fields do not participate in deduplication identity."""
    event_id = "66666666-6666-4666-8666-666666666666"
    schema = _make_schema()
    cartridge = DeduplicationCartridge()
    event = _make_event(event_type="test.event", payload={"id": "abc", "extra": "val"}, event_id=event_id)
    ctx = _make_context(schema=schema, key_exists=False)

    await cartridge.process(event, ctx)

    ctx.db.idempotency_key_exists.assert_called_once_with(event_id)
