# pylint: disable=invalid-name,unused-argument
"""Add last_conversation_injected_at column to sessions."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the conversation injection anchor used for transcript replay."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "last_conversation_injected_at" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN last_conversation_injected_at TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
