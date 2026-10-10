"""Clear obsolete in-place compaction stamps before launch attempts use session metadata."""

from __future__ import annotations

import aiosqlite

_CLEAR_OLD_COMPACTION_STAMPS_SQL = """
    UPDATE sessions
    SET idle_compaction_requested_at = NULL,
        idle_compaction_completed_at = NULL
"""


async def up(db: aiosqlite.Connection) -> None:
    """Retire the request/completion pair written by the in-place idle cycle."""
    await db.execute(_CLEAR_OLD_COMPACTION_STAMPS_SQL)
    await db.commit()
