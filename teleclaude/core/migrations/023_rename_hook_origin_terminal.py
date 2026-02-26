"""Rename legacy 'hook' input origin to canonical 'terminal'."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration: rewrite sessions.last_input_origin hook -> terminal."""
    await db.execute(
        """
        UPDATE sessions
        SET last_input_origin = 'terminal'
        WHERE last_input_origin = 'hook'
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Rollback migration: rewrite sessions.last_input_origin terminal -> hook."""
    await db.execute(
        """
        UPDATE sessions
        SET last_input_origin = 'hook'
        WHERE last_input_origin = 'terminal'
        """
    )
    await db.commit()
