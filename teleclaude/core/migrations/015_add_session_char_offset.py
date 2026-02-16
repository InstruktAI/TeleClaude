"""Add char_offset column to sessions for adapter-agnostic threaded output pagination."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add char_offset column to sessions table."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "char_offset" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN char_offset INTEGER DEFAULT 0")
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """char_offset column cannot be dropped in SQLite."""
