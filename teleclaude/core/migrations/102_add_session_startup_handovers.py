"""Create the durable session startup handover records."""

from __future__ import annotations

import aiosqlite

_CREATE_SESSION_STARTUP_HANDOVERS_SQL = """
CREATE TABLE IF NOT EXISTS session_startup_handovers (
    session_id TEXT PRIMARY KEY,
    launch_intent_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'accepted', 'agent_launched', 'submitting', 'reporting_uncertain',
        'handed_over', 'failed', 'delivery_uncertain'
    )),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
)
"""
_CREATE_STATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_session_startup_handovers_state
ON session_startup_handovers(state)
"""


async def up(db: aiosqlite.Connection) -> None:
    """Create the handover table and its state index for upgraded databases."""
    await db.execute(_CREATE_SESSION_STARTUP_HANDOVERS_SQL)
    await db.execute(_CREATE_STATE_INDEX_SQL)
    await db.commit()
