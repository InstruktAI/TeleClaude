"""Scope ephemeral UI message cleanup records to their owning adapter."""

from __future__ import annotations

import aiosqlite

_LEGACY_TABLE = "pending_message_deletions_unscoped"
_SCOPED_COLUMN = "adapter_key"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_CURRENT_COLUMNS_SQL = "PRAGMA table_info(pending_message_deletions)"

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


async def _current_table_is_unscoped(db: aiosqlite.Connection) -> bool:
    """Report whether the live table still carries rows no adapter owns."""
    async with db.execute(_CURRENT_COLUMNS_SQL) as cursor:  # guard: raw-sql
        columns = {str(row[1]) for row in await cursor.fetchall()}
    return bool(columns) and _SCOPED_COLUMN not in columns


async def up(db: aiosqlite.Connection) -> None:
    """Preserve unowned legacy rows explicitly while installing the scoped shape.

    Each statement of a script commits on its own, and the ledger row that
    retires this migration is written later still, so the schema itself has to
    say which work remains. A parked table means the unscoped rows await
    adoption; a live table already carrying the adapter column means every row
    has an owner and must never be parked again, since adoption would relabel
    those owners as unowned. The index the unscoped shape carries shares its
    name with the scoped one and travels with the rename, so it is dropped
    rather than assumed absent.
    """
    legacy_present = await _table_exists(db, _LEGACY_TABLE)
    if not legacy_present and await _current_table_is_unscoped(db):
        await db.executescript(_SET_ASIDE_SQL)  # guard: raw-sql
        legacy_present = True

    await db.executescript(_INSTALL_SQL)  # guard: raw-sql

    if legacy_present:
        await db.executescript(_ADOPT_LEGACY_ROWS_SQL)  # guard: raw-sql

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
