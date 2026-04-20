"""Add last_projected_output_digest column to sessions table.

Projection-owned assistant-output dedupe state. This remains separate from the
adapter delivery digest stored in last_output_digest.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the projection-owned assistant output digest column."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "last_projected_output_digest" in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN last_projected_output_digest TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
