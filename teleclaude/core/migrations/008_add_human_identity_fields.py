"""Add human identity fields to sessions."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add human_email and human_role to sessions."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "human_email" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN human_email TEXT")

    if "human_role" not in column_names:
        await db.execute("ALTER TABLE sessions ADD COLUMN human_role TEXT")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Remove human identity columns."""
    try:
        # SQLite >= 3.35.0 supports DROP COLUMN
        await db.execute("ALTER TABLE sessions DROP COLUMN human_email")
        await db.execute("ALTER TABLE sessions DROP COLUMN human_role")
        await db.commit()
    except Exception:
        pass  # Ignore if not supported or fails
