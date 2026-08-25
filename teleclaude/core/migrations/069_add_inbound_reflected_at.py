"""One-shot reflection consumption marker for delivered caller-originated rows."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "reflected_at"
_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN reflected_at TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the reflection-consumption timestamp to accepted inbound rows."""
    async with db.execute("PRAGMA table_info(inbound_queue)") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN_NAME not in columns:
        await db.execute(_COLUMN_SQL)  # guard: raw-sql
    await db.commit()
