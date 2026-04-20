"""Add one_shot column to session_listeners table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add one_shot flag to session_listeners."""
    await db.execute("ALTER TABLE session_listeners ADD COLUMN one_shot INTEGER NOT NULL DEFAULT 0")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
