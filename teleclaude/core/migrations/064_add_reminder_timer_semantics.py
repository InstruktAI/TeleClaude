"""Add profile-owned timer state and auto-cancel metadata."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Migrate reminder-owned state to the current timer semantics."""
    await db.executescript(
        """
        ALTER TABLE reminders ADD COLUMN sliding INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE reminders ADD COLUMN auto_cancel INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE reminders ADD COLUMN pending_answer_occurrence_key TEXT;
        ALTER TABLE reminders ADD COLUMN pending_answer_inbound_id INTEGER;
        ALTER TABLE reminders ADD COLUMN pending_answer_at TEXT;
        ALTER TABLE reminder_entries ADD COLUMN sliding INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE reminder_entries ADD COLUMN auto_cancel INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE reminder_entries ADD COLUMN cancel_reason TEXT;
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
