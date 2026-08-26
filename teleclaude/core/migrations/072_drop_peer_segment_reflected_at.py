"""Drop the peer-segment reflection marker left by an abandoned consumption lane."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "reflected_at"
_DROP_SQL = "ALTER TABLE peer_bundle_segments DROP COLUMN reflected_at"


async def up(db: aiosqlite.Connection) -> None:
    """Remove the column no reflection path reads."""
    async with db.execute("PRAGMA table_info(peer_bundle_segments)") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN_NAME in columns:
        await db.execute(_DROP_SQL)  # guard: raw-sql
    await db.commit()
