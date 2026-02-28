"""Tests for pipeline cartridges."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from teleclaude_events.cartridges import DeduplicationCartridge, NotificationProjectorCartridge
from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel
from teleclaude_events.pipeline import Pipeline, PipelineContext


def _make_catalog(
    event_type: str = "test.created",
    idempotency_fields: list[str] | None = None,
    lifecycle: NotificationLifecycle | None = None,
) -> EventCatalog:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type=event_type,
            description="Test event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=idempotency_fields or ["slug"],
            lifecycle=lifecycle or NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    return catalog


def _make_envelope(
    event: str = "test.created",
    slug: str = "my-task",
    idempotency_key: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event=event,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": slug},
        idempotency_key=idempotency_key,
    )


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_cartridges.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_dedup_passes_new_event(db: EventDB) -> None:
    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    dedup = DeduplicationCartridge()

    env = _make_envelope(slug="new-task")
    result = await dedup.process(env, context)

    assert result is not None
    assert result.event == "test.created"
    # idempotency_key should be set
    assert result.idempotency_key is not None


@pytest.mark.asyncio
async def test_dedup_drops_duplicate(db: EventDB) -> None:
    catalog = _make_catalog()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    dedup = DeduplicationCartridge()

    # First pass: set key in envelope and insert manually
    env = _make_envelope(slug="dup-task")
    first = await dedup.process(env, context)
    assert first is not None
    # Insert it so the key exists
    schema = catalog.get("test.created")
    assert schema is not None
    await db.insert_notification(first, schema)

    # Second pass: same event — should be dropped
    env2 = _make_envelope(slug="dup-task")
    result = await dedup.process(env2, context)
    assert result is None


@pytest.mark.asyncio
async def test_dedup_passes_through_no_idempotency_fields(db: EventDB) -> None:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.no_idem",
            description="No idempotency",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=[],
        )
    )
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    dedup = DeduplicationCartridge()

    env = EventEnvelope(event="test.no_idem", source="test", level=EventLevel.WORKFLOW)
    result = await dedup.process(env, context)
    assert result is not None


@pytest.mark.asyncio
async def test_projector_creates_notification(db: EventDB) -> None:
    catalog = _make_catalog()
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    projector = NotificationProjectorCartridge()

    env = _make_envelope(slug="proj-task", idempotency_key="test.created:proj-task")
    result = await projector.process(env, context)

    assert result is not None
    push_callback.assert_awaited_once()
    call_args = push_callback.call_args
    notification_id, event_type, was_created, _is_meaningful = call_args[0]
    assert was_created is True
    assert event_type == "test.created"
    assert notification_id > 0


@pytest.mark.asyncio
async def test_projector_passes_through_no_lifecycle(db: EventDB) -> None:
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.no_lifecycle",
            description="No lifecycle",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            lifecycle=None,
        )
    )
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    projector = NotificationProjectorCartridge()

    env = EventEnvelope(event="test.no_lifecycle", source="test", level=EventLevel.WORKFLOW)
    result = await projector.process(env, context)

    assert result is not None
    push_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_pipeline_dedup_then_projector(db: EventDB) -> None:
    catalog = _make_catalog()
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    pipeline = Pipeline([DeduplicationCartridge(), NotificationProjectorCartridge()], context)

    env = _make_envelope(slug="pipeline-task")
    result = await pipeline.execute(env)

    assert result is not None
    push_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_dropped_by_dedup_never_reaches_projector(db: EventDB) -> None:
    catalog = _make_catalog()
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    pipeline = Pipeline([DeduplicationCartridge(), NotificationProjectorCartridge()], context)

    # First pass: creates notification
    env1 = _make_envelope(slug="drop-task")
    result1 = await pipeline.execute(env1)
    assert result1 is not None
    push_callback.assert_awaited_once()
    push_callback.reset_mock()

    # Second pass with same slug: dedup drops it, projector never fires
    env2 = _make_envelope(slug="drop-task")
    result2 = await pipeline.execute(env2)
    assert result2 is None
    push_callback.assert_not_awaited()
