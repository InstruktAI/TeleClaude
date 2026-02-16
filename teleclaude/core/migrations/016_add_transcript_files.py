"""Add transcript_files column to sessions for multi-file transcript chain storage."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add transcript_files column to sessions table."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "transcript_files" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN transcript_files TEXT DEFAULT '[]'")
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """transcript_files column cannot be dropped in SQLite."""
