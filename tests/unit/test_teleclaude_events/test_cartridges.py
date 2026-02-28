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
    notification_id, event_type, _level, was_created, _is_meaningful = call_args[0]
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


# --- Notification projector: updates branch ---


@pytest.mark.asyncio
async def test_projector_updates_existing_by_group_key(db: EventDB) -> None:
    """updates-only lifecycle with group_key finds and updates the existing row."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.updated",
            description="Update event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                meaningful_fields=["status"],
            ),
        )
    )
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    projector = NotificationProjectorCartridge()

    # Seed an existing notification manually
    seed_schema = catalog.get("test.updated")
    assert seed_schema is not None
    seed_env = EventEnvelope(
        event="test.updated",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "status": "pending"},
        idempotency_key="test.updated:my-task",
    )
    existing_id = await db.insert_notification(seed_env, seed_schema)

    # Now process an update event
    update_env = EventEnvelope(
        event="test.updated",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "status": "active"},
    )
    result = await projector.process(update_env, context)

    assert result is not None
    push_callback.assert_awaited_once()
    # Notification should be the same row (not a new insert)
    call_args = push_callback.call_args[0]
    notification_id, _event_type, _level, was_created, is_meaningful = call_args
    assert notification_id == existing_id
    assert was_created is False
    # "status" is in meaningful_fields → is_meaningful
    assert is_meaningful is True


@pytest.mark.asyncio
async def test_projector_updates_creates_when_no_existing(db: EventDB) -> None:
    """updates-only lifecycle with group_key creates a row when none exists."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.updated",
            description="Update event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                meaningful_fields=["status"],
            ),
        )
    )
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    projector = NotificationProjectorCartridge()

    env = EventEnvelope(
        event="test.updated",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "new-task", "status": "active"},
    )
    result = await projector.process(env, context)

    assert result is not None
    push_callback.assert_awaited_once()
    call_args = push_callback.call_args[0]
    _notification_id, _event_type, _level, was_created, is_meaningful = call_args
    assert was_created is True
    assert is_meaningful is True


@pytest.mark.asyncio
async def test_projector_resolves_existing_by_group_key(db: EventDB) -> None:
    """resolves lifecycle with group_key marks existing notification resolved."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.created",
            description="Create event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="test.resolved",
            description="Resolve event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=[],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    projector = NotificationProjectorCartridge()

    # Seed an existing notification
    seed_schema = catalog.get("test.created")
    assert seed_schema is not None
    seed_env = EventEnvelope(
        event="test.created",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "resolve-task"},
        idempotency_key="test.created:resolve-task",
    )
    row_id = await db.insert_notification(seed_env, seed_schema)

    # Process resolve event
    resolve_env = EventEnvelope(
        event="test.resolved",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "resolve-task", "summary": "done"},
    )
    await projector.process(resolve_env, context)

    row = await db.get_notification(row_id)
    assert row is not None
    assert row["agent_status"] == "resolved"
    assert row["resolved_at"] is not None


@pytest.mark.asyncio
async def test_projector_creates_and_updates_with_group_key_updates_existing(db: EventDB) -> None:
    """creates+updates+group_key: second event updates the existing row by group_key."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.assessed",
            description="Assessment event",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug", "score"],
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="slug",
                meaningful_fields=["score"],
            ),
        )
    )
    push_callback = AsyncMock()
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[push_callback])
    projector = NotificationProjectorCartridge()

    # First event: no existing notification → creates
    env1 = EventEnvelope(
        event="test.assessed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "score": 80},
    )
    await projector.process(env1, context)
    push_callback.assert_awaited_once()
    first_call = push_callback.call_args[0]
    first_id = first_call[0]
    assert first_call[3] is True  # was_created

    push_callback.reset_mock()

    # Second event (different score → different idempotency key): should UPDATE the existing row
    env2 = EventEnvelope(
        event="test.assessed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "score": 90},
    )
    await projector.process(env2, context)
    push_callback.assert_awaited_once()
    second_call = push_callback.call_args[0]
    assert second_call[0] == first_id  # same notification row
    assert second_call[3] is False  # was_created=False (update, not insert)

    # Only one notification should exist for this slug
    rows = await db.list_notifications(domain="test")
    assert len(rows) == 1


# --- Dedup: updates-only pass-through ---


@pytest.mark.asyncio
async def test_dedup_passes_updates_only_schema_on_second_event(db: EventDB) -> None:
    """Updates-only schemas bypass dedup so subsequent events always reach the projector."""
    catalog = EventCatalog()
    catalog.register(
        EventSchema(
            event_type="test.artifact_changed",
            description="Artifact changed",
            default_level=EventLevel.WORKFLOW,
            domain="test",
            idempotency_fields=["slug", "artifact"],
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                meaningful_fields=["artifact"],
            ),
        )
    )
    context = PipelineContext(catalog=catalog, db=db, push_callbacks=[])
    dedup = DeduplicationCartridge()

    env1 = EventEnvelope(
        event="test.artifact_changed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "artifact": "plan.md"},
    )
    # Manually stamp and insert so key exists
    first = await dedup.process(env1, context)
    assert first is not None
    schema = catalog.get("test.artifact_changed")
    assert schema is not None
    await db.insert_notification(first, schema)

    # Second event with same key: must NOT be dropped (updates-only bypasses dedup)
    env2 = EventEnvelope(
        event="test.artifact_changed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "my-task", "artifact": "plan.md"},
    )
    result = await dedup.process(env2, context)
    assert result is not None  # not dropped
