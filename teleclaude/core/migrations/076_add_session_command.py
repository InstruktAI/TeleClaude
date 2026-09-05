"""Record dispatched command identity on every session row."""

from __future__ import annotations

import aiosqlite

_ADD_COMMAND_COLUMN_SQL = "ALTER TABLE sessions ADD COLUMN command TEXT"
_BACKFILL_COMMAND_SQL = (
    "UPDATE sessions SET command = substr(title, 2, instr(title || ' ', ' ') - 2) WHERE title LIKE '/%'"
)


async def up(db: aiosqlite.Connection) -> None:
    """Migrate presentation-stored command identity into the owned session record."""
    await db.execute(_ADD_COMMAND_COLUMN_SQL)
    await db.execute(_BACKFILL_COMMAND_SQL)
    await db.commit()
