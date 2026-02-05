"""Add last_output_digest column to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - add last_output_digest column."""
    # Check if column already exists
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "last_output_digest" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN last_output_digest TEXT")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration - SQLite doesn't support DROP COLUMN easily."""
    # SQLite doesn't support DROP COLUMN directly, would need table rebuild
    # For simplicity, we leave the column in place on downgrade
    pass
