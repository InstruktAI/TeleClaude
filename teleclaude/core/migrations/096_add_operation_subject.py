"""Add the subject and owner recorded by each operation receipt."""

from __future__ import annotations

import aiosqlite

_OPERATION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('operations')"
_ADD_OPERATION_SUBJECT_SQL = "ALTER TABLE operations ADD COLUMN subject TEXT"
_ADD_OPERATION_SUBJECT_OWNER_SQL = "ALTER TABLE operations ADD COLUMN subject_owner TEXT"
_OPERATION_SUBJECT_COLUMN = "subject"
_OPERATION_SUBJECT_OWNER_COLUMN = "subject_owner"


async def up(db: aiosqlite.Connection) -> None:
    """Add nullable subject columns when they are absent."""
    async with db.execute(_OPERATION_COLUMNS_SQL) as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _OPERATION_SUBJECT_COLUMN not in columns:
        await db.execute(_ADD_OPERATION_SUBJECT_SQL)
    if _OPERATION_SUBJECT_OWNER_COLUMN not in columns:
        await db.execute(_ADD_OPERATION_SUBJECT_OWNER_SQL)
    await db.commit()
