"""Persist agent status and parallel open tool calls on session rows."""

from __future__ import annotations

import aiosqlite

_ADD_AGENT_STATUS_COLUMNS_SQL = (
    "ALTER TABLE sessions ADD COLUMN agent_status TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE sessions ADD COLUMN agent_status_reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN agent_status_since TIMESTAMP",
    "ALTER TABLE sessions ADD COLUMN open_tool_calls TEXT NOT NULL DEFAULT '[]'",
)

_SEED_AGENT_STATUS_SQL = """
UPDATE sessions
SET agent_status = CASE
        WHEN closed_at IS NOT NULL OR lifecycle_status IN ('closing', 'closed') THEN 'idle'
        WHEN lifecycle_status = 'initializing' OR runtime_activity_at IS NULL THEN 'unknown'
        WHEN last_message_sent_at IS NOT NULL
            AND (last_agent_stop_at IS NULL OR julianday(last_message_sent_at) > julianday(last_agent_stop_at))
            AND (last_agent_idle_at IS NULL OR julianday(last_message_sent_at) > julianday(last_agent_idle_at))
            THEN 'active'
        ELSE 'idle'
    END,
    agent_status_reason = '',
    agent_status_since = CURRENT_TIMESTAMP,
    open_tool_calls = '[]'
"""


async def up(db: aiosqlite.Connection) -> None:
    """Add stored agent status and seed it once from the prior read rule."""
    for column_sql in _ADD_AGENT_STATUS_COLUMNS_SQL:
        await db.execute(column_sql)
    await db.execute(_SEED_AGENT_STATUS_SQL)
    await db.commit()
