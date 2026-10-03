"""Add the declared owner carried by session subjects."""

from __future__ import annotations

import aiosqlite

_SESSION_SUBJECT_OWNER_COLUMN = "subject_owner"
_SESSION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('sessions')"
_ADD_SESSION_SUBJECT_OWNER_SQL = "ALTER TABLE sessions ADD COLUMN subject_owner TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable column when it is absent."""
    async with db.execute(_SESSION_COLUMNS_SQL) as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _SESSION_SUBJECT_OWNER_COLUMN in columns:
        return
    await db.execute(_ADD_SESSION_SUBJECT_OWNER_SQL)
    await db.commit()
