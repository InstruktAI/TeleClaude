"""Drop the retired per-session authentication token ledger."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Remove the session token index and table from existing databases."""
    await db.execute("DROP INDEX IF EXISTS idx_session_tokens_session")
    await db.execute("DROP TABLE IF EXISTS session_tokens")
    await db.commit()
