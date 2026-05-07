"""Add turn_anchor_sha column to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the HEAD-at-turn-start SHA used for turn-anchored scoping."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "turn_anchor_sha" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN turn_anchor_sha TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
