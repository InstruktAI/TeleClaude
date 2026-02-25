"""Add degraded_until column to agent_availability table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - add degraded_until column."""
    # Check if column already exists
    cursor = await db.execute("PRAGMA table_info(agent_availability)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "degraded_until" not in column_names:
        await db.execute("ALTER TABLE agent_availability ADD COLUMN degraded_until TEXT")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration - SQLite doesn't support DROP COLUMN easily."""
    # SQLite doesn't support DROP COLUMN directly, would need table rebuild
    # For simplicity, we leave the column in place on downgrade
    pass
