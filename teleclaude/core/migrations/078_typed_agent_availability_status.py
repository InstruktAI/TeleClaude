"""Persist the typed availability state for agent and model subjects."""

from __future__ import annotations

import aiosqlite

_MIGRATION_SQL = """
CREATE TABLE agent_availability_typed (
    agent TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'available',
    status_until TEXT,
    reason TEXT,
    PRIMARY KEY (agent, model)
);

INSERT INTO agent_availability_typed (agent, model, status, status_until, reason)
SELECT
    agent,
    model,
    CASE
        WHEN reason LIKE 'degraded%' THEN 'degraded'
        WHEN available = 0 THEN 'unavailable'
        ELSE 'available'
    END,
    COALESCE(unavailable_until, degraded_until),
    CASE
        WHEN reason LIKE 'degraded:%' THEN substr(reason, length('degraded:') + 1)
        ELSE reason
    END
FROM agent_availability;

DROP TABLE agent_availability;
ALTER TABLE agent_availability_typed RENAME TO agent_availability;
"""
_FOREIGN_KEYS_OFF_SQL = "PRAGMA foreign_keys = OFF"
_FOREIGN_KEYS_ON_SQL = "PRAGMA foreign_keys = ON"


async def up(db: aiosqlite.Connection) -> None:
    """Move owned availability rows forward into the typed record shape."""
    await db.execute(_FOREIGN_KEYS_OFF_SQL)
    try:
        await db.executescript(_MIGRATION_SQL)
        await db.commit()
    finally:
        await db.execute(_FOREIGN_KEYS_ON_SQL)


async def down(db: aiosqlite.Connection) -> None:
    """Owned availability state migrates forward only."""
