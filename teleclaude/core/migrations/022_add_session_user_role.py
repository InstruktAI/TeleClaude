"""Add user_role column to sessions for context visibility filtering."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - add user_role column."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "user_role" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN user_role TEXT DEFAULT 'admin'")
    await db.execute("UPDATE sessions SET user_role='admin' WHERE user_role IS NULL OR TRIM(user_role) = ''")
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """user_role column cannot be dropped in SQLite."""
