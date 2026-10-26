"""Create the per-session turn ordinal table the completed-turns read records into."""

from __future__ import annotations

import aiosqlite

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT NOT NULL,
    turn_identity TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_identity),
    UNIQUE (session_id, ordinal)
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Install the table; it starts empty and fills as turns are first found."""
    await db.executescript(_CREATE_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
