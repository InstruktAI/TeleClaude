"""Drop the retired reminder projection cursor from native output consumers."""

from __future__ import annotations

import aiosqlite

_CURSOR_COLUMNS_SQL = "SELECT name FROM pragma_table_info('output_consumer_cursors')"
_REMOVED_COLUMN = "last_reminder_entry_id"
_CREATE_REBUILT_CURSORS_SQL = """
CREATE TABLE output_consumer_cursors_new (
    session_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    generation_id TEXT,
    char_offset INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, consumer)
)
"""
_COPY_CURSORS_SQL = """
INSERT INTO output_consumer_cursors_new (
    session_id, consumer, generation_id, char_offset, updated_at
)
SELECT session_id, consumer, generation_id, char_offset, updated_at
FROM output_consumer_cursors
"""


async def _cursor_columns(db: aiosqlite.Connection) -> set[str]:
    """Return the installed output-consumer cursor columns."""
    async with db.execute(_CURSOR_COLUMNS_SQL) as cursor:  # guard: raw-sql
        return {str(row[0]) for row in await cursor.fetchall()}


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild cursor state without the removed reminder projection column."""
    if _REMOVED_COLUMN not in await _cursor_columns(db):
        return
    await db.execute("PRAGMA foreign_keys = OFF")  # guard: raw-sql
    try:
        await db.execute("BEGIN")  # guard: raw-sql
        await db.execute(_CREATE_REBUILT_CURSORS_SQL)  # guard: raw-sql
        await db.execute(_COPY_CURSORS_SQL)  # guard: raw-sql
        await db.execute("DROP TABLE output_consumer_cursors")  # guard: raw-sql
        await db.execute("ALTER TABLE output_consumer_cursors_new RENAME TO output_consumer_cursors")  # guard: raw-sql
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys = ON")  # guard: raw-sql


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
