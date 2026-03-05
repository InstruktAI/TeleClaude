"""Tests for the classification cartridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.cartridges.classification import ClassificationCartridge
from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext


def _make_context(catalog: EventCatalog, db: EventDB) -> PipelineContext:
    return PipelineContext(catalog=catalog, db=db)


def _make_event(event: str = "test.event") -> EventEnvelope:
    return EventEnvelope(event=event, source="test", level=EventLevel.WORKFLOW)


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_classification.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_known_lifecycle_schema_notification_worthy(db: EventDB) -> None:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.event",
            description="test",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    ctx = _make_context(catalog, db)
    cartridge = ClassificationCartridge()

    result = await cartridge.process(_make_event(), ctx)

    assert result is not None
    assert result.payload["_classification"]["treatment"] == "notification-worthy"


@pytest.mark.asyncio
async def test_actionable_schema_flagged(db: EventDB) -> None:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.event",
            description="test",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    ctx = _make_context(catalog, db)
    cartridge = ClassificationCartridge()

    result = await cartridge.process(_make_event(), ctx)

    assert result is not None
    assert result.payload["_classification"]["actionable"] is True


@pytest.mark.asyncio
async def test_no_lifecycle_schema_signal_only(db: EventDB) -> None:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.event",
            description="test",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            lifecycle=None,
        )
    )
    ctx = _make_context(catalog, db)
    cartridge = ClassificationCartridge()

    result = await cartridge.process(_make_event(), ctx)

    assert result is not None
    assert result.payload["_classification"]["treatment"] == "signal-only"


@pytest.mark.asyncio
async def test_unknown_event_type_signal_only(db: EventDB) -> None:
    catalog = EventCatalog()  # Empty catalog — no schema for "test.event"
    ctx = _make_context(catalog, db)
    cartridge = ClassificationCartridge()

    result = await cartridge.process(_make_event(), ctx)

    assert result is not None
    assert result.payload["_classification"]["treatment"] == "signal-only"
    assert result.payload["_classification"]["actionable"] is False


@pytest.mark.asyncio
async def test_classification_appended_to_payload(db: EventDB) -> None:
    catalog = EventCatalog()
    ctx = _make_context(catalog, db)
    cartridge = ClassificationCartridge()

    event = EventEnvelope(
        event="any.event", source="test", level=EventLevel.WORKFLOW, payload={"existing_key": "value"}
    )
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_classification" in result.payload
    assert result.payload["existing_key"] == "value"  # Original payload preserved
