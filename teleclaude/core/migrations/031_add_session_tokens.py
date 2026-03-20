"""Add session_tokens table for agent session authentication."""
# pylint: disable=invalid-name  # Migration filenames are versioned on purpose.

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create session_tokens table."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS session_tokens (
            token TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            principal TEXT NOT NULL,
            role TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_session_tokens_session ON session_tokens(session_id)")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop session_tokens table."""
    await db.execute("DROP INDEX IF EXISTS idx_session_tokens_session")
    await db.execute("DROP TABLE IF EXISTS session_tokens")
    await db.commit()
