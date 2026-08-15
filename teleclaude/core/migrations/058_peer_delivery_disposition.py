"""Add durable directional dispositions for unprocessable peer delivery."""

from __future__ import annotations

import aiosqlite

_DISPOSITION_COLUMNS = (
    "disposition",
    "disposition_entry_ref",
    "disposition_reason",
)
_ALTER_COLUMN_SQL = "ALTER TABLE conversation_delivery_state ADD COLUMN {column} TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the owned delivery-disposition fields without disturbing cursors."""
    async with db.execute("PRAGMA table_info(conversation_delivery_state)") as cursor:
        existing_columns = {str(row[1]) for row in await cursor.fetchall()}
    for column in _DISPOSITION_COLUMNS:
        if column not in existing_columns:
            await db.execute(_ALTER_COLUMN_SQL.format(column=column))  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
