"""Add the identity facts used to scope memory observations."""

from __future__ import annotations

import aiosqlite

_MEMORY_COLUMNS_SQL = "SELECT name FROM pragma_table_info('memory_observations')"
_ADD_MEMORY_SUBJECT_SQL = "ALTER TABLE memory_observations ADD COLUMN subject TEXT"
_ADD_MEMORY_SUBJECT_OWNER_SQL = "ALTER TABLE memory_observations ADD COLUMN subject_owner TEXT"
_ADD_MEMORY_PRINCIPAL_SQL = "ALTER TABLE memory_observations ADD COLUMN principal TEXT"
_MEMORY_SUBJECT_COLUMN = "subject"
_MEMORY_SUBJECT_OWNER_COLUMN = "subject_owner"
_MEMORY_PRINCIPAL_COLUMN = "principal"


async def up(db: aiosqlite.Connection) -> None:
    """Add nullable visibility columns when they are absent."""
    async with db.execute(_MEMORY_COLUMNS_SQL) as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _MEMORY_SUBJECT_COLUMN not in columns:
        await db.execute(_ADD_MEMORY_SUBJECT_SQL)
    if _MEMORY_SUBJECT_OWNER_COLUMN not in columns:
        await db.execute(_ADD_MEMORY_SUBJECT_OWNER_SQL)
    if _MEMORY_PRINCIPAL_COLUMN not in columns:
        await db.execute(_ADD_MEMORY_PRINCIPAL_SQL)
    await db.commit()
