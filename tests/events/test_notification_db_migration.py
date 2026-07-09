"""Forward migration for the `notifications.recipient` column.

A pre-recipient `notifications` table (no `recipient` column) must migrate
additively on `EventDB.initialize()`: the column appears, an old-shape row
reads back with `recipient=None`, and a new write persists a recipient.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

pytestmark = pytest.mark.functional

_EVENT_TYPE = "notification.escalation"
_RECIPIENT = "operator-a"
_RECIPIENT_COL = "recipient"


def _build_pre_recipient_schema(db_path: Path) -> None:
    """Create a `notifications` table at the pre-`recipient` schema with one row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE notifications ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, "
            "version INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL, level INTEGER NOT NULL, "
            "domain TEXT NOT NULL DEFAULT '', visibility TEXT NOT NULL DEFAULT 'local', "
            "entity TEXT, description TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}', "
            "idempotency_key TEXT, human_status TEXT NOT NULL DEFAULT 'unseen', "
            "agent_status TEXT NOT NULL DEFAULT 'none', agent_id TEXT, resolution TEXT, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, seen_at TEXT, claimed_at TEXT, "
            "resolved_at TEXT, UNIQUE(idempotency_key))"
        )
        conn.execute(
            "INSERT INTO notifications "
            "(event_type, source, level, description, payload, created_at, updated_at) "
            "VALUES ('notification.escalation', 'test', 20, 'legacy row', '{}', 'now', 'now')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_recipient_column_added_additively_on_old_shape_db(tmp_path: Path) -> None:
    """Initializing over a pre-`recipient` DB adds the column without losing the old row."""
    db_path = tmp_path / "events.sqlite"
    _build_pre_recipient_schema(db_path)

    db = EventDB(db_path)
    try:
        await db.initialize()

        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(notifications)")}
            assert _RECIPIENT_COL in columns
            row = conn.execute("SELECT description, recipient FROM notifications").fetchone()
            assert row == ("legacy row", None)
        finally:
            conn.close()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_recipient_persists_on_new_write_after_migration(tmp_path: Path) -> None:
    """A write after migrating an old-shape DB persists a recipient."""
    db_path = tmp_path / "events.sqlite"
    _build_pre_recipient_schema(db_path)

    db = EventDB(db_path)
    try:
        await db.initialize()
        envelope = EventEnvelope(
            event=_EVENT_TYPE,
            source="test",
            level=EventLevel.BUSINESS,
            domain="notification",
            visibility=EventVisibility.LOCAL,
            payload={},
        )
        notification_id = await db.insert_notification(envelope, recipient=_RECIPIENT)

        row = await db.get_notification(notification_id)
        assert row is not None
        assert row["recipient"] == _RECIPIENT
    finally:
        await db.close()
