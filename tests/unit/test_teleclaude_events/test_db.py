"""Tests for EventDB SQLite storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope, EventLevel


def _make_schema(event_type: str = "test.created") -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="Test event",
        default_level=EventLevel.WORKFLOW,
        domain="test",
        idempotency_fields=["slug"],
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
    )


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
        idempotency_key=idempotency_key or f"{event}:{slug}",
    )


@pytest.fixture
async def db(tmp_path: Path) -> EventDB:  # type: ignore[misc]
    event_db = EventDB(db_path=tmp_path / "test_events.db")
    await event_db.init()
    yield event_db  # type: ignore[misc]
    await event_db.close()


@pytest.mark.asyncio
async def test_init_creates_table(tmp_path: Path) -> None:
    event_db = EventDB(db_path=tmp_path / "test.db")
    await event_db.init()
    # Basic check: can insert without error
    schema = _make_schema()
    env = _make_envelope()
    row_id = await event_db.insert_notification(env, schema)
    assert row_id > 0
    await event_db.close()


@pytest.mark.asyncio
async def test_insert_and_get(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="task-a")
    row_id = await db.insert_notification(env, schema)
    row = await db.get_notification(row_id)
    assert row is not None
    assert row["event_type"] == "test.created"
    assert row["human_status"] == "unseen"
    assert row["agent_status"] == "none"
    assert row["domain"] == "test"


@pytest.mark.asyncio
async def test_get_missing_returns_none(db: EventDB) -> None:
    result = await db.get_notification(99999)
    assert result is None


@pytest.mark.asyncio
async def test_list_with_filters(db: EventDB) -> None:
    schema = _make_schema()
    await db.insert_notification(_make_envelope(slug="a"), schema)
    await db.insert_notification(_make_envelope(slug="b", event="test.other", idempotency_key="test.other:b"), schema)

    # Filter by domain
    rows = await db.list_notifications(domain="test")
    assert len(rows) == 2

    # Filter by human_status
    rows = await db.list_notifications(human_status="unseen")
    assert len(rows) == 2

    rows = await db.list_notifications(human_status="seen")
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_update_human_status(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="task-seen")
    row_id = await db.insert_notification(env, schema)

    success = await db.update_human_status(row_id, "seen")
    assert success is True

    row = await db.get_notification(row_id)
    assert row is not None
    assert row["human_status"] == "seen"
    assert row["seen_at"] is not None


@pytest.mark.asyncio
async def test_update_agent_status(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="task-claimed")
    row_id = await db.insert_notification(env, schema)

    success = await db.update_agent_status(row_id, "claimed", "agent-123")
    assert success is True

    row = await db.get_notification(row_id)
    assert row is not None
    assert row["agent_status"] == "claimed"
    assert row["agent_id"] == "agent-123"
    assert row["claimed_at"] is not None


@pytest.mark.asyncio
async def test_resolve_notification(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="task-resolved")
    row_id = await db.insert_notification(env, schema)

    resolution = {"summary": "Done", "resolved_by": "agent-1"}
    success = await db.resolve_notification(row_id, resolution)
    assert success is True

    row = await db.get_notification(row_id)
    assert row is not None
    assert row["agent_status"] == "resolved"
    assert row["resolved_at"] is not None


@pytest.mark.asyncio
async def test_upsert_creates_new(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="new-task", idempotency_key="test.created:new-task")
    row_id, was_created = await db.upsert_by_idempotency_key(env, schema)
    assert was_created is True
    assert row_id > 0


@pytest.mark.asyncio
async def test_upsert_updates_existing(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="existing-task", idempotency_key="test.created:existing")
    row_id1, was_created = await db.upsert_by_idempotency_key(env, schema)
    assert was_created is True

    # Same idempotency key — should update
    env2 = EventEnvelope(
        event="test.created",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="test",
        payload={"slug": "existing-task", "updated": True},
        idempotency_key="test.created:existing",
    )
    row_id2, was_created2 = await db.upsert_by_idempotency_key(env2, schema)
    assert was_created2 is False
    assert row_id2 == row_id1


@pytest.mark.asyncio
async def test_idempotency_key_exists(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="idem-task", idempotency_key="unique-key-123")
    await db.insert_notification(env, schema)

    assert await db.idempotency_key_exists("unique-key-123") is True
    assert await db.idempotency_key_exists("non-existent-key") is False


@pytest.mark.asyncio
async def test_find_by_group_key(db: EventDB) -> None:
    schema = _make_schema()
    env = _make_envelope(slug="group-task")
    await db.insert_notification(env, schema)

    row = await db.find_by_group_key("slug", "group-task")
    assert row is not None
    assert row["event_type"] == "test.created"

    missing = await db.find_by_group_key("slug", "nonexistent")
    assert missing is None


@pytest.mark.asyncio
async def test_update_notification_fields_with_reset(db: EventDB) -> None:
    """reset_human_status=True resets human_status to 'unseen'."""
    schema = _make_schema()
    env = _make_envelope(slug="fields-task")
    row_id = await db.insert_notification(env, schema)

    # Mark as seen first
    await db.update_human_status(row_id, "seen")
    row = await db.get_notification(row_id)
    assert row is not None
    assert row["human_status"] == "seen"

    # Update fields with reset: human_status should flip back to unseen
    success = await db.update_notification_fields(
        row_id,
        "Updated description",
        {"slug": "fields-task", "extra": True},
        reset_human_status=True,
    )
    assert success is True
    row = await db.get_notification(row_id)
    assert row is not None
    assert row["human_status"] == "unseen"
    assert row["description"] == "Updated description"


@pytest.mark.asyncio
async def test_update_notification_fields_without_reset(db: EventDB) -> None:
    """reset_human_status=False preserves existing human_status."""
    schema = _make_schema()
    env = _make_envelope(slug="silent-task")
    row_id = await db.insert_notification(env, schema)

    # Mark as seen
    await db.update_human_status(row_id, "seen")

    # Update fields without reset: human_status stays 'seen'
    success = await db.update_notification_fields(
        row_id,
        "Silent update",
        {"slug": "silent-task"},
        reset_human_status=False,
    )
    assert success is True
    row = await db.get_notification(row_id)
    assert row is not None
    assert row["human_status"] == "seen"
    assert row["description"] == "Silent update"


@pytest.mark.asyncio
async def test_update_agent_status_preserves_claimed_at(db: EventDB) -> None:
    """Transitioning from 'claimed' to 'in_progress' must not erase claimed_at."""
    schema = _make_schema()
    env = _make_envelope(slug="audit-task")
    row_id = await db.insert_notification(env, schema)

    # Claim the notification
    await db.update_agent_status(row_id, "claimed", "agent-1")
    row_claimed = await db.get_notification(row_id)
    assert row_claimed is not None
    assert row_claimed["claimed_at"] is not None
    original_claimed_at = row_claimed["claimed_at"]

    # Transition to in_progress: claimed_at must be preserved
    await db.update_agent_status(row_id, "in_progress", "agent-1")
    row_progress = await db.get_notification(row_id)
    assert row_progress is not None
    assert row_progress["agent_status"] == "in_progress"
    assert row_progress["claimed_at"] == original_claimed_at
