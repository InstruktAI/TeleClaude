"""Add durable operations table for receipt-backed long-running workflows."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create operations table and indexes."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS operations (
            operation_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            caller_session_id TEXT NOT NULL,
            client_request_id TEXT,
            cwd TEXT NOT NULL,
            slug TEXT,
            payload_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'completed', 'failed', 'stale', 'cancelled')),
            progress_phase TEXT,
            progress_decision TEXT,
            progress_reason TEXT,
            result_text TEXT,
            error_text TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            heartbeat_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_request_dedupe
            ON operations(kind, caller_session_id, client_request_id)
            WHERE client_request_id IS NOT NULL
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_operations_owner_state
            ON operations(caller_session_id, kind, state, created_at DESC)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_operations_state_heartbeat
            ON operations(state, heartbeat_at)
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop operations table and indexes."""
    await db.execute("DROP INDEX IF EXISTS idx_operations_state_heartbeat")
    await db.execute("DROP INDEX IF EXISTS idx_operations_owner_state")
    await db.execute("DROP INDEX IF EXISTS idx_operations_request_dedupe")
    await db.execute("DROP TABLE IF EXISTS operations")
    await db.commit()
