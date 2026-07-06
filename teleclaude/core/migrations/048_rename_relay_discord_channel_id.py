"""Rename sessions.relay_discord_channel_id to relay_channel_id."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Rename the owned relay-channel column off its platform-specific name."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        rows = await cursor.fetchall()
    columns = {str(row[0]) for row in rows}
    if "relay_channel_id" in columns:
        return

    await db.execute("ALTER TABLE sessions RENAME COLUMN relay_discord_channel_id TO relay_channel_id")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
