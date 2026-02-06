"""Add agent output tracking columns to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - add agent output tracking columns."""
    # Check existing columns
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_agent_output_at" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN last_agent_output_at TEXT")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration - SQLite doesn't support DROP COLUMN easily."""
    pass
