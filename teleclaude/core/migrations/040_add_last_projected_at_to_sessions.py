"""Add last_projected_at column to sessions table.

Projection-owned watermark: only the transcript projector writes this field.
Used for dedupe instead of the mixed-purpose last_message_sent_at.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the projection-owned watermark column."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "last_projected_at" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN last_projected_at TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
