"""Give sessions the stamps the conversation idle cycle keeps: compaction requested, completed, and the close."""

from __future__ import annotations

import aiosqlite

_SESSION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('sessions')"
_ADD_COLUMN_SQL_TEMPLATE = "ALTER TABLE sessions ADD COLUMN {column} TEXT"
_IDLE_COMPACTION_COLUMNS = ("idle_compaction_requested_at", "idle_compaction_completed_at", "idle_closed_at")


async def up(db: aiosqlite.Connection) -> None:
    """Add each nullable column that is absent."""
    async with db.execute(_SESSION_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    for column in _IDLE_COMPACTION_COLUMNS:
        if column not in existing:
            await db.execute(_ADD_COLUMN_SQL_TEMPLATE.format(column=column))
    await db.commit()
