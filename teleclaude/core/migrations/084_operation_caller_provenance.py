"""Widen operations for caller-less submission and the caller-provenance block."""

from __future__ import annotations

import aiosqlite

_CREATE_OPERATIONS_TABLE = """
CREATE TABLE operations_new (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    caller_session_id TEXT,
    caller_computer TEXT,
    caller_provenance_json TEXT,
    client_request_id TEXT,
    cwd TEXT,
    slug TEXT,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'completed', 'failed', 'stale', 'cancelled')),
    progress_phase TEXT,
    progress_decision TEXT,
    progress_reason TEXT,
    result_text TEXT,
    error_text TEXT,
    error_payload TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    heartbeat_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0
)
"""
_COPY_OPERATIONS_ROWS = """
INSERT INTO operations_new (
    operation_id, kind, caller_session_id, client_request_id, cwd, slug, payload_json,
    state, progress_phase, progress_decision, progress_reason, result_text, error_text,
    error_payload, created_at, updated_at, started_at, completed_at, heartbeat_at, attempt_count
)
SELECT
    operation_id, kind, caller_session_id, client_request_id, cwd, slug, payload_json,
    state, progress_phase, progress_decision, progress_reason, result_text, error_text,
    error_payload, created_at, updated_at, started_at, completed_at, heartbeat_at, attempt_count
FROM operations
"""
_CREATE_OPERATIONS_INDEXES = """
CREATE INDEX idx_operations_owner_state ON operations(caller_session_id, kind, state, created_at DESC);
CREATE UNIQUE INDEX idx_operations_request_dedupe ON operations(kind, caller_session_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE INDEX idx_operations_state_heartbeat ON operations(state, heartbeat_at);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild operations with nullable caller_session_id/cwd and a caller-provenance block."""
    async with db.execute("SELECT name FROM pragma_table_info('operations')") as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if "caller_computer" in columns:
        return

    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute(_CREATE_OPERATIONS_TABLE)
        await db.execute(_COPY_OPERATIONS_ROWS)
        await db.execute("DROP TABLE operations")
        await db.execute("ALTER TABLE operations_new RENAME TO operations")
        await db.executescript(_CREATE_OPERATIONS_INDEXES)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
