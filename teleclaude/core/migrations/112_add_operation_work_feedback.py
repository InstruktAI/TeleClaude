"""Add declared work-feedback storage to durable operations."""

from __future__ import annotations

import aiosqlite

WORK_FEEDBACK_COLUMN = "work_feedback"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable declaration column to existing operation rows."""
    async with db.execute("SELECT name FROM pragma_table_info('operations')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if WORK_FEEDBACK_COLUMN in columns:
        return

    await db.execute("ALTER TABLE operations ADD COLUMN work_feedback TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
