"""Drop the retired session event-subscription records."""

from __future__ import annotations

import aiosqlite

_DROP_SESSION_INDEX_SQL = "DROP INDEX IF EXISTS idx_event_subscriptions_session_id"
_DROP_EVENT_TYPE_INDEX_SQL = "DROP INDEX IF EXISTS idx_event_subscriptions_event_type"
_DROP_TABLE_SQL = "DROP TABLE IF EXISTS event_subscriptions"


async def up(db: aiosqlite.Connection) -> None:
    """Remove the table no session code reads or writes, with its indexes."""
    await db.execute(_DROP_SESSION_INDEX_SQL)  # guard: raw-sql
    await db.execute(_DROP_EVENT_TYPE_INDEX_SQL)  # guard: raw-sql
    await db.execute(_DROP_TABLE_SQL)  # guard: raw-sql
    await db.commit()
