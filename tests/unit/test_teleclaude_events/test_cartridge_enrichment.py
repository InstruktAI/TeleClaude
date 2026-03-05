"""Tests for the enrichment cartridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.cartridges.enrichment import EnrichmentCartridge
from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import PipelineContext


def _make_context(db: EventDB) -> PipelineContext:
    return PipelineContext(catalog=EventCatalog(), db=db)


def _make_event(entity: str | None = None) -> EventEnvelope:
    return EventEnvelope(event="test.happened", source="test", level=EventLevel.WORKFLOW, entity=entity)


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_enrichment.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


def _make_schema(event_type: str) -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="test",
        default_level=EventLevel.WORKFLOW,
        domain="test",
        lifecycle=NotificationLifecycle(creates=True),
    )


@pytest.mark.asyncio
async def test_no_entity_passthrough(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    event = _make_event(entity=None)
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_unknown_entity_type_passthrough(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    event = _make_event(entity="http://example.com/foo")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_todo_entity_enriched(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    # Seed the DB with a build completion event for the entity
    schema = _make_schema("domain.software-development.build.completed")
    ctx.catalog.register(schema)
    env = EventEnvelope(
        event="domain.software-development.build.completed",
        source="daemon",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        entity="telec://todo/my-task",
        payload={"success": False},
    )
    await db.insert_notification(env, schema)

    event = _make_event(entity="telec://todo/my-task")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_enrichment" in result.payload
    assert "failure_count" in result.payload["_enrichment"]
    assert result.payload["_enrichment"]["failure_count"] == 1


@pytest.mark.asyncio
async def test_todo_successful_build_not_counted_as_failure(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    # Seed with a successful build — must not count as failure
    schema = _make_schema("domain.software-development.build.completed")
    ctx.catalog.register(schema)
    env = EventEnvelope(
        event="domain.software-development.build.completed",
        source="daemon",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        entity="telec://todo/my-task",
        payload={"success": True},
    )
    await db.insert_notification(env, schema)

    event = _make_event(entity="telec://todo/my-task")
    result = await cartridge.process(event, ctx)

    # No failures → no enrichment (failure_count == 0 and no other data)
    assert result is not None
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_todo_no_history_no_enrichment(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    # No DB rows for this entity
    event = _make_event(entity="telec://todo/empty-task")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_enrichment" not in result.payload


@pytest.mark.asyncio
async def test_worker_entity_enriched(db: EventDB) -> None:
    ctx = _make_context(db)
    cartridge = EnrichmentCartridge()

    # Seed with worker crash events
    schema = _make_schema("system.worker.crashed")
    ctx.catalog.register(schema)
    env = EventEnvelope(
        event="system.worker.crashed",
        source="daemon",
        level=EventLevel.OPERATIONAL,
        domain="system",
        entity="telec://worker/my-worker",
        payload={"worker_name": "my-worker", "timestamp": "2024-01-01T10:00:00"},
    )
    await db.insert_notification(env, schema)

    event = _make_event(entity="telec://worker/my-worker")
    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_enrichment" in result.payload
    enrichment = result.payload["_enrichment"]
    assert "crash_count" in enrichment
    assert enrichment["crash_count"] == 1
    assert "last_crash_at" in enrichment
