"""Create the record of which transcript files of a session a completed-turns read has taken turns from."""

from __future__ import annotations

import aiosqlite

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS session_turn_sources (
    session_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, source_digest)
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Install the table; it starts empty and fills as the completed-turns read takes each file."""
    await db.executescript(_CREATE_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
