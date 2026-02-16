"""Add bookkeeping and relay columns to sessions for help desk platform."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add bookkeeping and relay columns to sessions table."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    for col in (
        "last_memory_extraction_at",
        "help_desk_processed_at",
        "relay_status",
        "relay_discord_channel_id",
        "relay_started_at",
    ):
        if col not in column_names:
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")  # noqa: S608
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:  # noqa: ARG001
    """Relay columns cannot be dropped in SQLite."""
