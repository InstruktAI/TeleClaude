"""Add producer-owned control delivery deduplication keys."""

from __future__ import annotations

import aiosqlite

_SOURCE_KEY_COLUMN = "source_key"
_COLUMNS_SQL = "SELECT name FROM pragma_table_info('control_outbox')"
_ADD_COLUMN_SQL = "ALTER TABLE control_outbox ADD COLUMN source_key TEXT"
_BACKFILL_SQL = "UPDATE control_outbox SET source_key = 'legacy:' || id WHERE source_key IS NULL"
_INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS idx_control_outbox_source_key ON control_outbox(source_key)"


async def up(db: aiosqlite.Connection) -> None:
    """Migrate existing rows to stable synthetic source keys before enforcing uniqueness."""
    async with db.execute(_COLUMNS_SQL) as cursor:  # guard: raw-sql
        rows = await cursor.fetchall()
    if _SOURCE_KEY_COLUMN not in {str(row[0]) for row in rows}:
        await db.execute(_ADD_COLUMN_SQL)  # guard: raw-sql
        await db.execute(_BACKFILL_SQL)  # guard: raw-sql
    await db.execute(_INDEX_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
