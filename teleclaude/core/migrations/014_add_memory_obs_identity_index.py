"""Add composite index on memory_observations(project, identity_key)."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create identity-scoped memory lookup index."""
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_identity ON memory_observations(project, identity_key)")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop the identity index."""
    await db.execute("DROP INDEX IF EXISTS idx_memory_obs_identity")
    await db.commit()
