"""Characterization tests for teleclaude.events.cartridges.classification."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.events.cartridges.classification import ClassificationCartridge
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


def _make_context(schema: EventSchema | None = None) -> MagicMock:
    catalog = MagicMock(spec=EventCatalog)
    catalog.get.return_value = schema
    ctx = MagicMock()
    ctx.catalog = catalog
    return ctx


def _make_schema(
    event_type: str = "test.event",
    actionable: bool = False,
    lifecycle: NotificationLifecycle | None = None,
) -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="test schema",
        default_level=EventLevel.OPERATIONAL,
        domain="test",
        actionable=actionable,
        lifecycle=lifecycle,
    )


@pytest.mark.asyncio
async def test_unknown_event_gets_signal_only_treatment():
    """Unknown event type receives signal-only treatment and actionable=False."""
    cartridge = ClassificationCartridge()
    event = _make_event("unknown.event")
    ctx = _make_context(schema=None)

    result = await cartridge.process(event, ctx)

    assert result is not None
    classification = result.payload["_classification"]
    assert classification["treatment"] == "signal-only"
    assert classification["actionable"] is False


@pytest.mark.asyncio
async def test_known_event_without_lifecycle_gets_signal_only():
    """Event with schema but no lifecycle gets signal-only treatment."""
    schema = _make_schema(lifecycle=None)
    cartridge = ClassificationCartridge()
    event = _make_event()
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not None
    classification = result.payload["_classification"]
    assert classification["treatment"] == "signal-only"


@pytest.mark.asyncio
async def test_known_event_with_lifecycle_gets_notification_worthy():
    """Event with schema and lifecycle gets notification-worthy treatment."""
    lifecycle = NotificationLifecycle(creates=True)
    schema = _make_schema(lifecycle=lifecycle)
    cartridge = ClassificationCartridge()
    event = _make_event()
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not None
    classification = result.payload["_classification"]
    assert classification["treatment"] == "notification-worthy"


@pytest.mark.asyncio
async def test_actionable_flag_propagated_from_schema():
    """Actionable flag is taken from schema, not hardcoded."""
    schema = _make_schema(actionable=True)
    cartridge = ClassificationCartridge()
    event = _make_event()
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.payload["_classification"]["actionable"] is True


@pytest.mark.asyncio
async def test_existing_payload_fields_preserved():
    """Original payload fields are preserved after classification annotation."""
    schema = _make_schema()
    cartridge = ClassificationCartridge()
    event = _make_event(payload={"key": "value", "count": 42})
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert result.payload["key"] == "value"
    assert result.payload["count"] == 42


@pytest.mark.asyncio
async def test_returns_new_envelope_not_mutate_original():
    """Process returns a new envelope — original event is not mutated."""
    schema = _make_schema()
    cartridge = ClassificationCartridge()
    event = _make_event(payload={"x": 1})
    ctx = _make_context(schema=schema)

    result = await cartridge.process(event, ctx)

    assert result is not event
    assert "_classification" not in event.payload
