"""Persist per-generation firing ordinals for reminder history."""

from __future__ import annotations

import aiosqlite

_REMINDERS_TABLE = "reminders"
_REMINDER_ENTRIES_TABLE = "reminder_entries"
_FIRING_COUNT_COLUMN = "firing_count"
_FIRING_NUMBER_COLUMN = "firing_number"
_ADD_FIRING_COUNT = "ALTER TABLE reminders ADD COLUMN firing_count INTEGER NOT NULL DEFAULT 0 CHECK(firing_count >= 0)"
_ADD_FIRING_NUMBER = (
    "ALTER TABLE reminder_entries ADD COLUMN firing_number INTEGER CHECK(firing_number IS NULL OR firing_number > 0)"
)
_TABLE_COLUMNS_QUERY = "SELECT name FROM pragma_table_info('{table}')"
_BACKFILL_SQL = """
    UPDATE reminder_entries
    SET firing_number = (
        SELECT COUNT(*)
        FROM reminder_entries AS prior
        WHERE prior.session_id = reminder_entries.session_id
          AND prior.slug = reminder_entries.slug
          AND prior.generation = reminder_entries.generation
          AND prior.transition = 'firing'
          AND prior.entry_id <= reminder_entries.entry_id
    )
    WHERE transition = 'firing';

    UPDATE reminders
    SET firing_count = COALESCE(
        (
            SELECT MAX(firing_number)
            FROM reminder_entries
            WHERE reminder_entries.session_id = reminders.session_id
              AND reminder_entries.slug = reminders.slug
              AND reminder_entries.generation = reminders.generation
        ),
        0
    );
"""


async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(_TABLE_COLUMNS_QUERY.format(table=table)) as cursor:
        rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


async def up(db: aiosqlite.Connection) -> None:
    """Bring reminder aggregates and entries forward to ordinal-aware state."""
    if _FIRING_COUNT_COLUMN not in await _table_columns(db, _REMINDERS_TABLE):
        await db.execute(_ADD_FIRING_COUNT)
    if _FIRING_NUMBER_COLUMN not in await _table_columns(db, _REMINDER_ENTRIES_TABLE):
        await db.execute(_ADD_FIRING_NUMBER)
    await db.executescript(_BACKFILL_SQL)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
