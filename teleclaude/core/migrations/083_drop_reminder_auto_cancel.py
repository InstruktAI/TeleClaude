"""Drop the retired reminder auto-cancel correlation columns."""

from __future__ import annotations

import aiosqlite

_REMINDERS_COLUMNS = (
    "auto_cancel",
    "pending_answer_occurrence_key",
    "pending_answer_inbound_id",
    "pending_answer_at",
)
_REMINDER_ENTRIES_COLUMNS = ("auto_cancel", "cancel_reason")


async def up(db: aiosqlite.Connection) -> None:
    """Remove the columns no retirement decision reads."""
    async with db.execute("PRAGMA table_info(reminders)") as cursor:
        reminders_columns = {str(row[1]) for row in await cursor.fetchall()}
    for column in _REMINDERS_COLUMNS:
        if column in reminders_columns:
            await db.execute(f"ALTER TABLE reminders DROP COLUMN {column}")  # guard: raw-sql
    async with db.execute("PRAGMA table_info(reminder_entries)") as cursor:
        reminder_entries_columns = {str(row[1]) for row in await cursor.fetchall()}
    for column in _REMINDER_ENTRIES_COLUMNS:
        if column in reminder_entries_columns:
            await db.execute(f"ALTER TABLE reminder_entries DROP COLUMN {column}")  # guard: raw-sql
    await db.commit()
