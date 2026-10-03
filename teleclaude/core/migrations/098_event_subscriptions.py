"""Create durable event-subscription records."""

from __future__ import annotations

import aiosqlite

_CREATE_EVENT_SUBSCRIPTIONS_SQL = """
CREATE TABLE IF NOT EXISTS event_subscriptions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('once', 'every')),
    narrowing_json TEXT NOT NULL,
    created_position TEXT NOT NULL,
    principal TEXT NOT NULL,
    company TEXT,
    claimed_event_id TEXT,
    created_at TEXT NOT NULL
)
"""
_CREATE_SESSION_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_event_subscriptions_session_id
ON event_subscriptions(session_id)
"""
_CREATE_EVENT_TYPE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_event_subscriptions_event_type
ON event_subscriptions(event_type)
"""


async def up(db: aiosqlite.Connection) -> None:
    """Create the subscription table and lookup indexes for upgraded databases."""
    await db.execute(_CREATE_EVENT_SUBSCRIPTIONS_SQL)
    await db.execute(_CREATE_SESSION_INDEX_SQL)
    await db.execute(_CREATE_EVENT_TYPE_INDEX_SQL)
    await db.commit()
