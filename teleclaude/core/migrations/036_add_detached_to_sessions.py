# pylint: disable=invalid-name,unused-argument
"""Add detached column to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the detached flag used to flatten daemon-spawned sessions in the TUI."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "detached" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN detached INTEGER NOT NULL DEFAULT 0")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
