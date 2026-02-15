"""Add identity_key column to memory_observations for identity-scoped memory."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add identity_key column and index."""
    cursor = await db.execute("PRAGMA table_info(memory_observations)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "identity_key" not in column_names:
        await db.execute("ALTER TABLE memory_observations ADD COLUMN identity_key TEXT")

    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_identity ON memory_observations(project, identity_key)")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Remove identity_key index (column cannot be dropped in SQLite)."""
    await db.execute("DROP INDEX IF EXISTS idx_memory_identity")
    await db.commit()
