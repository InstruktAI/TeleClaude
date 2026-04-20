"""Add last_agent_stop_at column to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the stop timestamp used for deterministic turn-settled checks."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "last_agent_stop_at" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN last_agent_stop_at TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
