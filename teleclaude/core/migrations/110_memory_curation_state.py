"""Give stored memory observations the state, retirement time and source session curation needs.

The idle sweep stamped every session's extraction marker without extracting anything, so the stamps record
no read: each session's read point is cleared once.
"""

from __future__ import annotations

import aiosqlite

_OBSERVATION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('memory_observations')"
_ADD_COLUMN_SQLS = {
    "state": "ALTER TABLE memory_observations ADD COLUMN state TEXT NOT NULL DEFAULT 'current'",
    "retired_at": "ALTER TABLE memory_observations ADD COLUMN retired_at TEXT",
    "source_session_id": "ALTER TABLE memory_observations ADD COLUMN source_session_id TEXT",
}
_CLEAR_UNREAD_STAMPS_SQL = (
    "UPDATE sessions SET last_memory_extraction_at = NULL WHERE last_memory_extraction_at IS NOT NULL"
)
_CREATE_SOURCE_SESSION_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_memory_obs_source_session ON memory_observations(source_session_id)"
)


async def up(db: aiosqlite.Connection) -> None:
    """Add each absent column, every stored observation staying current, index the source session, clear the stamps."""
    async with db.execute(_OBSERVATION_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    for column, statement in _ADD_COLUMN_SQLS.items():
        if column not in existing:
            await db.execute(statement)
    await db.execute(_CREATE_SOURCE_SESSION_INDEX_SQL)
    await db.execute(_CLEAR_UNREAD_STAMPS_SQL)
    await db.commit()
