"""Add visibility column to sessions for role-based access control."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add visibility column to sessions table."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "visibility" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN visibility TEXT DEFAULT 'private'")
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """visibility column cannot be dropped in SQLite."""
