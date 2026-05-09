"""Drop dead session_metadata column from sessions."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Drop the dormant metadata blob column when present."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "session_metadata" not in columns:
        return

    await db.execute("ALTER TABLE sessions DROP COLUMN session_metadata")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
