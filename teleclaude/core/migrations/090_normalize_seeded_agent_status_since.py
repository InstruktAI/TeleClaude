"""Rewrite agent-status timestamps seeded by migration 089 into the ORM's stored form."""

from __future__ import annotations

import aiosqlite

# Migration 089 seeded `agent_status_since` with SQLite's CURRENT_TIMESTAMP
# (`YYYY-MM-DD HH:MM:SS`), while the ORM binds and stores datetimes with
# microseconds (`YYYY-MM-DD HH:MM:SS.ffffff`). Conditional updates that match on
# the stored value never match the seeded form.
_NORMALIZE_SEEDED_SINCE_SQL = """
UPDATE sessions
SET agent_status_since = agent_status_since || '.000000'
WHERE agent_status_since IS NOT NULL
    AND length(agent_status_since) = 19
"""


async def up(db: aiosqlite.Connection) -> None:
    """Append the microsecond field to every second-precision agent-status timestamp."""
    await db.execute(_NORMALIZE_SEEDED_SINCE_SQL)
    await db.commit()
