"""Persist the presentation-only caller-origin prefix boundary."""

from __future__ import annotations

import aiosqlite

_PREFIX_COLUMN = "caller_origin_prefix_len"
_ALTER_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN caller_origin_prefix_len INTEGER"


async def up(db: aiosqlite.Connection) -> None:
    """Add the boundary to owned accepted-input rows."""
    async with db.execute("PRAGMA table_info(inbound_queue)") as cursor:
        existing_columns = {str(row[1]) for row in await cursor.fetchall()}
    if _PREFIX_COLUMN not in existing_columns:
        await db.execute(_ALTER_COLUMN_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
