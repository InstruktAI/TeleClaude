"""Add the native-command idle boundary to sessions."""

from __future__ import annotations

import aiosqlite

_ADD_COLUMN = "ALTER TABLE sessions ADD COLUMN last_agent_idle_at TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable boundary recorded after a completed native command."""
    await db.execute(_ADD_COLUMN)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
