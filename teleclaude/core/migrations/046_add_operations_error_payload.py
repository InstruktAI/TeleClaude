"""Add structured operation failure payload storage."""

from __future__ import annotations

import aiosqlite

ERROR_PAYLOAD_COLUMN = "error_payload"


async def up(db: aiosqlite.Connection) -> None:
    """Add nullable structured error payloads to operations."""
    async with db.execute("SELECT name FROM pragma_table_info('operations')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if ERROR_PAYLOAD_COLUMN in columns:
        return

    await db.execute("ALTER TABLE operations ADD COLUMN error_payload TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
