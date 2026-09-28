"""Add agent-status write versions and store notification gates as JSON arrays."""

from __future__ import annotations

import aiosqlite

_AGENT_STATUS_VERSION_COLUMN = "agent_status_version"
_AGENT_STATUS_VERSION_LOOKUP_SQL = "SELECT 1 FROM pragma_table_info('sessions') WHERE name = ?"

_ADD_AGENT_STATUS_VERSION_SQL = "ALTER TABLE sessions ADD COLUMN agent_status_version INTEGER NOT NULL DEFAULT 0"

_MIGRATE_TURN_NOTIFICATIONS_SQL = """
UPDATE sessions
SET turn_notifications_sent = CASE
    WHEN turn_notifications_sent IS NULL OR turn_notifications_sent = '' THEN '[]'
    ELSE '["' || replace(turn_notifications_sent, ',', '","') || '"]'
END
WHERE turn_notifications_sent IS NULL OR substr(turn_notifications_sent, 1, 1) != '['
"""


async def up(db: aiosqlite.Connection) -> None:
    """Add the write version and migrate notification records to JSON arrays."""
    result = await db.execute(_AGENT_STATUS_VERSION_LOOKUP_SQL, (_AGENT_STATUS_VERSION_COLUMN,))
    if await result.fetchone() is None:
        await db.execute(_ADD_AGENT_STATUS_VERSION_SQL)
    await db.execute(_MIGRATE_TURN_NOTIFICATIONS_SQL)
    await db.commit()
