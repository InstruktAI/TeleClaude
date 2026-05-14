"""Targeted tests for the get_event_db factory lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import teleclaude.events.db as event_db_module
from teleclaude.events import EventDB, get_event_db
from teleclaude.events.envelope import EventEnvelope, EventLevel


@pytest.fixture(autouse=True)
def isolate_event_db_singleton(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Force the factory to build into a tmp directory and start with no cache."""
    monkeypatch.setattr(event_db_module, "EVENTS_DB_PATH", tmp_path / "events.db")
    monkeypatch.setattr(event_db_module, "_event_db_instance", None)


@pytest.mark.asyncio
async def test_get_event_db_returns_initialized_singleton(tmp_path: Path) -> None:
    first = await get_event_db()
    assert isinstance(first, EventDB)
    assert first.is_initialized()
    # Observable isolation: the factory used the monkeypatched path, so the
    # tmp DB file is the one created on disk (defaults resolve at call time).
    assert (tmp_path / "events.db").exists()
    second = await get_event_db()
    assert second is first
    await first.close()


@pytest.mark.asyncio
async def test_get_event_db_replaces_closed_cached_instance() -> None:
    """A closed instance must not be handed out as if initialized.

    This also covers the ``close`` -> factory-cache-cleared invariant: if
    the cache were not cleared, the second call would hand back the closed
    instance instead of an initialized one.
    """
    first = await get_event_db()
    await first.close()
    assert not first.is_initialized()
    second = await get_event_db()
    assert second is not first
    assert second.is_initialized()
    await second.close()


@pytest.mark.asyncio
async def test_cleanup_runtime_events_deletes_only_resolved_and_reviewed_expired_rows(tmp_path: Path) -> None:
    database = EventDB(tmp_path / "events.db")
    await database.initialize()
    old_iso = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    recent_iso = datetime.now(UTC).isoformat()
    try:
        old_resolved_id = await database.insert_notification(
            EventEnvelope(
                event="system.old_resolved",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
            )
        )
        recent_resolved_id = await database.insert_notification(
            EventEnvelope(
                event="system.recent_resolved",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
            )
        )
        unresolved_id = await database.insert_notification(
            EventEnvelope(
                event="system.unresolved",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
            )
        )
        await database.resolve_notification(old_resolved_id, {"state": "done"})
        await database.resolve_notification(recent_resolved_id, {"state": "done"})
        await database._db().execute(
            "UPDATE notifications SET resolved_at = ?, updated_at = ? WHERE id = ?",
            (old_iso, old_iso, old_resolved_id),
        )
        await database._db().execute(
            "UPDATE notifications SET created_at = ?, updated_at = ? WHERE id = ?",
            (old_iso, old_iso, unresolved_id),
        )
        await database._db().execute(
            "UPDATE notifications SET resolved_at = ?, updated_at = ? WHERE id = ?",
            (recent_iso, recent_iso, recent_resolved_id),
        )

        old_reviewed_id = await database.quarantine_event(
            EventEnvelope(
                event="system.old_reviewed",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
                timestamp=datetime.now(UTC) - timedelta(days=8),
            ),
            flags=[],
        )
        recent_reviewed_id = await database.quarantine_event(
            EventEnvelope(
                event="system.recent_reviewed",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
            ),
            flags=[],
        )
        unreviewed_id = await database.quarantine_event(
            EventEnvelope(
                event="system.unreviewed",
                source="test",
                level=EventLevel.OPERATIONAL,
                domain="system",
                timestamp=datetime.now(UTC) - timedelta(days=8),
            ),
            flags=[],
        )
        await database._db().execute(
            "UPDATE quarantined_events SET reviewed = 1, received_at = ? WHERE id = ?",
            (old_iso, old_reviewed_id),
        )
        await database._db().execute(
            "UPDATE quarantined_events SET reviewed = 1, received_at = ? WHERE id = ?",
            (recent_iso, recent_reviewed_id),
        )
        await database._db().commit()

        deleted = await database.cleanup_runtime_events(older_than=datetime.now(UTC) - timedelta(days=7))

        assert deleted == 2
        assert await database.get_notification(old_resolved_id) is None
        assert await database.get_notification(recent_resolved_id) is not None
        assert await database.get_notification(unresolved_id) is not None
        reviewed_rows = await database.list_quarantined(reviewed=True)
        unreviewed_rows = await database.list_quarantined(reviewed=False)
        assert [row["id"] for row in reviewed_rows] == [recent_reviewed_id]
        assert [row["id"] for row in unreviewed_rows] == [unreviewed_id]
    finally:
        await database.close()
