"""Scope ephemeral UI message cleanup records to their owning adapter."""

from __future__ import annotations

import aiosqlite

_MIGRATION_SQL = """
DROP TABLE IF EXISTS pending_message_deletions;

CREATE TABLE pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    adapter_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, adapter_key, message_id, deletion_type),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX idx_pending_deletions_session
    ON pending_message_deletions(session_id, adapter_key);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Replace unowned ephemeral rows with the adapter-scoped current shape."""
    await db.executescript(_MIGRATION_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
