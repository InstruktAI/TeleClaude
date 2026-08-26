"""Add last_input column to sessions table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add the human-visible span of the accepted turn.

    Additive and null by default. An existing row carries only the accepted-input
    fingerprint, which is truncated and so cannot be resolved back into a visible
    span; those rows fill on their next accepted turn.
    """
    await db.execute("ALTER TABLE sessions ADD COLUMN last_input TEXT")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
