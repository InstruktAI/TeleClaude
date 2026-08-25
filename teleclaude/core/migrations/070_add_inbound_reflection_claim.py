"""Separate the recoverable reflection claim from the finalized receipt."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "reflection_claimed_at"
_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN reflection_claimed_at TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the expiring reflection-claim timestamp to accepted inbound rows."""
    async with db.execute("PRAGMA table_info(inbound_queue)") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN_NAME not in columns:
        await db.execute(_COLUMN_SQL)  # guard: raw-sql
    await db.commit()
