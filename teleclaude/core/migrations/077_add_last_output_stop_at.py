"""Add the stop version belonging to retained final output."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "last_output_stop_at"
_SESSIONS_TABLE = "sessions"
_TABLE_COLUMNS_SQL = "SELECT name FROM pragma_table_info('sessions')"
_ADD_COLUMN_SQL = "ALTER TABLE sessions ADD COLUMN last_output_stop_at TEXT"
_BACKFILL_OUTPUT_VERSION_SQL = (
    "UPDATE sessions SET last_output_stop_at = last_agent_stop_at "
    "WHERE last_output_raw IS NOT NULL AND last_agent_stop_at IS NOT NULL"
)


async def up(db: aiosqlite.Connection) -> None:
    """Add and backfill the retained output's existing stop version."""
    async with db.execute(_TABLE_COLUMNS_SQL) as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if _COLUMN_NAME in columns:
        return
    await db.execute(_ADD_COLUMN_SQL)
    await db.execute(_BACKFILL_OUTPUT_VERSION_SQL)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
