"""Retain admitted operation identity without inventing principals for legacy rows."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO = "PRAGMA table_info(operations)"
_COLUMN = "caller_principal"
_ADD = "ALTER TABLE operations ADD COLUMN caller_principal TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Legacy absence remains absence; this migration resolves no ambient identity."""
    cursor = await db.execute(_TABLE_INFO)
    columns = await cursor.fetchall()
    if not any(column[1] == _COLUMN for column in columns):
        await db.execute(_ADD)
    await db.commit()
