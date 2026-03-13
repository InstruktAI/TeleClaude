"""Add session_tokens table for agent session authentication."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create session_tokens table with session and expiry indexes."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS session_tokens (
            token TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            principal TEXT NOT NULL,
            role TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_session_tokens_session ON session_tokens(session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_session_tokens_expires ON session_tokens(expires_at)")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop session_tokens table (no-op for safety in production)."""
    # SQLite supports DROP TABLE — safe to reverse this migration if needed.
    await db.execute("DROP INDEX IF EXISTS idx_session_tokens_expires")
    await db.execute("DROP INDEX IF EXISTS idx_session_tokens_session")
    await db.execute("DROP TABLE IF EXISTS session_tokens")
    await db.commit()
