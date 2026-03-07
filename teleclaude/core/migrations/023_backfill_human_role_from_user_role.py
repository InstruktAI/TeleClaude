"""Backfill human_role from legacy user_role values when human_role is missing."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Copy legacy user_role values into human_role for existing rows."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = {col[1] for col in columns}

    if "human_role" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN human_role TEXT")

    if "user_role" in column_names:
        await db.execute(
            """
            UPDATE sessions
            SET human_role = LOWER(TRIM(user_role))
            WHERE (human_role IS NULL OR TRIM(human_role) = '')
              AND user_role IS NOT NULL
              AND TRIM(user_role) != ''
            """
        )

    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """Backfill is irreversible."""
