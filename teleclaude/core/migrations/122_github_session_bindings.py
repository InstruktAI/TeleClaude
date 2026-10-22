"""Retain infrastructure-owned GitHub actor/work assignments with session state."""

from __future__ import annotations

import aiosqlite

_CREATE_BINDINGS = """
CREATE TABLE IF NOT EXISTS github_session_bindings (
    session_id TEXT PRIMARY KEY,
    binding_json TEXT NOT NULL,
    native_target_json TEXT
)
"""


async def up(db: aiosqlite.Connection) -> None:
    """Add assignment storage without changing any existing session or credential."""
    await db.execute(_CREATE_BINDINGS)
    await db.commit()
