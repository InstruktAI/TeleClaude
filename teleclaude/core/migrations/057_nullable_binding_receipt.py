"""Allow receipt-less native turn bindings and retain measured conflict candidates."""

from __future__ import annotations

import aiosqlite

_CREATE_BINDINGS_TABLE = """
CREATE TABLE accepted_turn_bindings_new (
    binding_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    inbound_queue_id INTEGER,
    injected_span_start INTEGER,
    injected_span_end INTEGER,
    native_runtime TEXT,
    native_session_id TEXT,
    native_entry_id TEXT,
    created_at TEXT NOT NULL
)
"""
_COPY_BINDINGS_ROWS = """
INSERT INTO accepted_turn_bindings_new (
    binding_id, session_id, inbound_queue_id, injected_span_start,
    injected_span_end, native_runtime, native_session_id, native_entry_id, created_at
)
SELECT
    binding_id, session_id, inbound_queue_id, injected_span_start,
    injected_span_end, native_runtime, native_session_id, native_entry_id, created_at
FROM accepted_turn_bindings
"""
_CREATE_BINDING_INDEXES = """
CREATE UNIQUE INDEX idx_accepted_turn_bindings_inbound
ON accepted_turn_bindings(inbound_queue_id);
CREATE INDEX idx_accepted_turn_bindings_session
ON accepted_turn_bindings(session_id);
CREATE UNIQUE INDEX idx_accepted_turn_bindings_native_entry
ON accepted_turn_bindings(native_runtime, native_session_id, native_entry_id)
WHERE native_entry_id IS NOT NULL;
"""
_CREATE_CONFLICT_CANDIDATES = """
CREATE TABLE IF NOT EXISTS binding_conflict_candidates (
    inbound_queue_id INTEGER NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (inbound_queue_id, native_runtime, native_session_id, native_entry_id)
);
CREATE INDEX IF NOT EXISTS idx_binding_conflict_candidates_native_entry
ON binding_conflict_candidates(native_runtime, native_session_id, native_entry_id);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild bindings with a nullable receipt and create durable conflict identities."""
    async with db.execute("SELECT name FROM pragma_table_info('accepted_turn_bindings')") as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if "inbound_queue_id" not in columns:
        return

    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute(_CREATE_BINDINGS_TABLE)
        await db.execute(_COPY_BINDINGS_ROWS)
        await db.execute("DROP TABLE accepted_turn_bindings")
        await db.execute("ALTER TABLE accepted_turn_bindings_new RENAME TO accepted_turn_bindings")
        await db.executescript(_CREATE_BINDING_INDEXES)
        await db.executescript(_CREATE_CONFLICT_CANDIDATES)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
