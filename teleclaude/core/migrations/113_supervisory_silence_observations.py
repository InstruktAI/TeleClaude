"""Add run identity and current caller identity to supervision records."""

from __future__ import annotations

from uuid import uuid4

import aiosqlite

_SESSION_COLUMNS = (
    ("runtime_run_id", "ALTER TABLE sessions ADD COLUMN runtime_run_id TEXT"),
    ("runtime_turn_id", "ALTER TABLE sessions ADD COLUMN runtime_turn_id TEXT"),
)
_LISTENER_COLUMNS = (
    ("caller_computer", "ALTER TABLE session_listeners ADD COLUMN caller_computer TEXT"),
    ("startup_run_id", "ALTER TABLE session_listeners ADD COLUMN startup_run_id TEXT"),
)
_SESSION_TABLE_INFO_SQL = "PRAGMA table_info(sessions)"
_LISTENER_TABLE_INFO_SQL = "PRAGMA table_info(session_listeners)"
_RESTORE_SILENCE_ONLY_STATUS_SQL = """
UPDATE sessions
SET agent_status = CASE agent_status_reason
        WHEN 'no_start' THEN 'unknown'
        WHEN 'no_signal' THEN 'active'
    END,
    agent_status_reason = '',
    agent_status_since = NULL,
    agent_status_version = agent_status_version + 1
WHERE agent_status = 'stalled'
  AND agent_status_reason IN ('no_start', 'no_signal')
"""
_RETAINED_ACTIVE_SESSIONS_SQL = """
SELECT session_id
FROM sessions
WHERE agent_status = 'active'
  AND (runtime_run_id IS NULL OR runtime_turn_id IS NULL)
"""
_BACKFILL_ACTIVE_GENERATIONS_SQL = """
UPDATE sessions
SET runtime_run_id = COALESCE(runtime_run_id, ?),
    runtime_turn_id = COALESCE(runtime_turn_id, ?)
WHERE session_id = ?
  AND agent_status = 'active'
"""


async def _table_columns(db: aiosqlite.Connection, query: str) -> set[str]:
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
    return {str(row[1]) for row in rows}


async def up(db: aiosqlite.Connection) -> None:
    """Add run-scoped supervision fields and retain active observation eligibility."""
    session_columns = await _table_columns(db, _SESSION_TABLE_INFO_SQL)
    for column, statement in _SESSION_COLUMNS:
        if column not in session_columns:
            await db.execute(statement)

    listener_columns = await _table_columns(db, _LISTENER_TABLE_INFO_SQL)
    for column, statement in _LISTENER_COLUMNS:
        if column not in listener_columns:
            await db.execute(statement)
    async with db.execute(_RETAINED_ACTIVE_SESSIONS_SQL) as cursor:
        active_rows = await cursor.fetchall()
    for (session_id,) in active_rows:
        await db.execute(
            _BACKFILL_ACTIVE_GENERATIONS_SQL,
            (str(uuid4()), str(uuid4()), session_id),
        )
    await db.execute(_RESTORE_SILENCE_ONLY_STATUS_SQL)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
