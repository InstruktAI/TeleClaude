"""Add the recorded configuration subject to sessions."""

from __future__ import annotations

import aiosqlite

_SESSION_CONFIG_SUBJECT_COLUMN = "config_subject"
_SESSION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('sessions')"
_ADD_SESSION_CONFIG_SUBJECT_SQL = "ALTER TABLE sessions ADD COLUMN config_subject TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable column when it is absent."""
    async with db.execute(_SESSION_COLUMNS_SQL) as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _SESSION_CONFIG_SUBJECT_COLUMN in columns:
        return
    await db.execute(_ADD_SESSION_CONFIG_SUBJECT_SQL)
    await db.commit()
