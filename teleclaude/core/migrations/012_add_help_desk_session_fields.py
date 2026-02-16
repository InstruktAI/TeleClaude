"""Add help desk bookkeeping and relay columns to sessions table.

New columns: last_memory_extraction_at, help_desk_processed_at,
relay_status, relay_discord_channel_id, relay_started_at.
Also adds human_email and human_role if missing from older databases.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns = await cursor.fetchall()
    existing = {col[1] for col in columns}

    new_columns = [
        ("last_memory_extraction_at", "TEXT"),
        ("help_desk_processed_at", "TEXT"),
        ("relay_status", "TEXT"),
        ("relay_discord_channel_id", "TEXT"),
        ("relay_started_at", "TEXT"),
        ("human_email", "TEXT"),
        ("human_role", "TEXT"),
    ]

    for name, col_type in new_columns:
        if name not in existing:
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {name} {col_type}")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    pass  # SQLite does not support DROP COLUMN in older versions; no-op
