"""Scope ephemeral UI message cleanup records to their owning adapter."""

from __future__ import annotations

import aiosqlite

_CURRENT_TABLE = "pending_message_deletions"
_LEGACY_TABLE = "pending_message_deletions_unscoped"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

_SET_ASIDE_SQL = """
ALTER TABLE pending_message_deletions RENAME TO pending_message_deletions_unscoped;
"""

_INSTALL_SQL = """
DROP INDEX IF EXISTS idx_pending_deletions_session;

CREATE TABLE IF NOT EXISTS pending_message_deletions (
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

_ADOPT_LEGACY_ROWS_SQL = """
INSERT OR IGNORE INTO pending_message_deletions (
    session_id,
    adapter_key,
    message_id,
    deletion_type,
    created_at
)
SELECT
    session_id,
    'legacy-unscoped',
    message_id,
    deletion_type,
    created_at
FROM pending_message_deletions_unscoped;

DROP TABLE pending_message_deletions_unscoped;
"""


async def _table_exists(db: aiosqlite.Connection, name: str) -> bool:
    """Report whether the named table is present in this schema."""
    async with db.execute(_TABLE_EXISTS_SQL, (name,)) as cursor:  # guard: raw-sql
        return await cursor.fetchone() is not None


async def up(db: aiosqlite.Connection) -> None:
    """Preserve unowned legacy rows explicitly while installing the scoped shape.

    Each statement of a script commits on its own, so the set-aside table is the
    marker of how far a prior pass reached: its presence means the unscoped rows
    are already parked and only adoption remains. The index the unscoped shape
    carries shares its name with the scoped one and travels with the rename, so
    it is dropped rather than assumed absent.
    """
    legacy_present = await _table_exists(db, _LEGACY_TABLE)
    if not legacy_present and await _table_exists(db, _CURRENT_TABLE):
        await db.executescript(_SET_ASIDE_SQL)  # guard: raw-sql
        legacy_present = True

    await db.executescript(_INSTALL_SQL)  # guard: raw-sql

    if legacy_present:
        await db.executescript(_ADOPT_LEGACY_ROWS_SQL)  # guard: raw-sql

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
