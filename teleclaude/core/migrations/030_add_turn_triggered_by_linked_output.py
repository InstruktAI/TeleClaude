"""Add turn_triggered_by_linked_output flag for echo suppression."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add boolean column to track linked-output-triggered turns."""
    await db.execute("ALTER TABLE sessions ADD COLUMN turn_triggered_by_linked_output BOOLEAN NOT NULL DEFAULT 0")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Remove turn_triggered_by_linked_output column (SQLite limitation: recreate table)."""
    # SQLite < 3.35.0 does not support DROP COLUMN; no-op for safety.
