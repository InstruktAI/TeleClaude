"""Drop the unread terminal_size column from sessions."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO_SQL = "PRAGMA table_info(sessions)"
_COLUMN = "terminal_size"
_DROP_SQL = "ALTER TABLE sessions DROP COLUMN terminal_size"


async def up(db: aiosqlite.Connection) -> None:
    """Remove the column no session code reads or writes."""
    async with db.execute(_TABLE_INFO_SQL) as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN in columns:
        await db.execute(_DROP_SQL)  # guard: raw-sql
    await db.commit()
