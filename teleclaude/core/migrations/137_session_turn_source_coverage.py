"""Record how far a session's completions were covered when a read took a transcript file."""

from __future__ import annotations

import aiosqlite

_TABLE = "session_turn_sources"
_ADD_STOP_SQL = f"ALTER TABLE {_TABLE} ADD COLUMN stop_at TEXT"
_ADD_TAIL_SQL = f"ALTER TABLE {_TABLE} ADD COLUMN tail_open INTEGER NOT NULL DEFAULT 0"
_COLUMNS_SQL = f"PRAGMA table_info({_TABLE})"
_NAME_COLUMN = 1


async def up(db: aiosqlite.Connection) -> None:
    """Add the coverage columns once; files recorded before them read as covered by no stop and a settled tail."""
    async with db.execute(_COLUMNS_SQL) as cursor:
        present = {str(row[_NAME_COLUMN]) for row in await cursor.fetchall()}
    if "stop_at" not in present:
        await db.execute(_ADD_STOP_SQL)  # guard: raw-sql
    if "tail_open" not in present:
        await db.execute(_ADD_TAIL_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
