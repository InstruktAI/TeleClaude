"""Add the durable per-person voice-focus table."""

from __future__ import annotations

import aiosqlite

_VOICE_FOCUS_SQL = """
CREATE TABLE IF NOT EXISTS voice_focus (
    person_slug TEXT PRIMARY KEY,
    focus_id TEXT NOT NULL,
    focused_session_id TEXT,
    basis TEXT NOT NULL DEFAULT 'derived' CHECK(basis IN ('derived', 'explicit')),
    set_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Install the voice_focus table."""
    await db.executescript(_VOICE_FOCUS_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
