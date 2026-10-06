"""Track whether an inbound row has encountered an occupied composer."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "was_held"
_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN was_held INTEGER NOT NULL DEFAULT 0"
_COMPOSER_OCCUPIED_REASON = "composer_occupied"
_BACKFILL_SQL = """
UPDATE inbound_queue
SET was_held = 1
WHERE status IN ('pending', 'failed', 'processing')
  AND last_error = ?
"""


async def up(db: aiosqlite.Connection) -> None:
    """Add the durable hold fact and recover open rows last known to be held."""
    async with db.execute("PRAGMA table_info(inbound_queue)") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN_NAME not in columns:
        await db.execute(_COLUMN_SQL)  # guard: raw-sql
    await db.execute(_BACKFILL_SQL, (_COMPOSER_OCCUPIED_REASON,))
    await db.commit()
