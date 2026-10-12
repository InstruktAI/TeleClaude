"""Give sessions a soft-deletion timestamp so removal retains the record, its identity and its lineage."""

from __future__ import annotations

import aiosqlite

_SESSION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('sessions')"
_ADD_DELETED_AT_SQL = "ALTER TABLE sessions ADD COLUMN deleted_at TIMESTAMP"
_DELETED_AT_COLUMN = "deleted_at"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable soft-deletion column when it is absent; every stored session stays undeleted."""
    async with db.execute(_SESSION_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    if _DELETED_AT_COLUMN not in existing:
        await db.execute(_ADD_DELETED_AT_SQL)
    await db.commit()
