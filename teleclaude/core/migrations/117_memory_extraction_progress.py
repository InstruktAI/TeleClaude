"""Give memory its own extraction state: closures, extractions and per-source progress.

Progress belongs to each source conversation, not to a person: the read point the session record carried is
seeded once as that conversation's time bound, and the session column is removed. Observations gain a reference
to the extraction that produced them.
"""

from __future__ import annotations

import aiosqlite

_COLUMNS_SQL = "SELECT name FROM pragma_table_info('{table}')"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_BEGIN_SQL = "BEGIN"
_CREATE_TABLES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS memory_closures (
        id TEXT PRIMARY KEY,
        source_session_id TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        identity_key TEXT NOT NULL,
        desk TEXT,
        home_kind TEXT NOT NULL,
        home_slug TEXT NOT NULL,
        extraction_id TEXT,
        pending_reason TEXT,
        settled_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_closures_source ON memory_closures(source_session_id, ended_at)",
    "CREATE INDEX IF NOT EXISTS idx_memory_closures_extraction ON memory_closures(extraction_id)",
    """
    CREATE TABLE IF NOT EXISTS memory_extractions (
        id TEXT PRIMARY KEY,
        source_session_id TEXT NOT NULL,
        identity_key TEXT NOT NULL,
        desk TEXT,
        home_kind TEXT NOT NULL,
        home_slug TEXT NOT NULL,
        from_key TEXT,
        through_key TEXT,
        through_at TEXT,
        message_count INTEGER NOT NULL DEFAULT 0,
        missing_sources TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_extractions_source ON memory_extractions(source_session_id, status)",
    """
    CREATE TABLE IF NOT EXISTS memory_source_progress (
        source_session_id TEXT PRIMARY KEY,
        through_key TEXT,
        through_at TEXT,
        time_bound TEXT,
        updated_at TEXT NOT NULL
    )
    """,
)
_ADD_EXTRACTION_ID_SQL = "ALTER TABLE memory_observations ADD COLUMN extraction_id TEXT"
_EXTRACTION_ID_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_memory_obs_extraction ON memory_observations(extraction_id)"
_SEED_PROGRESS_SQL = """
    INSERT OR IGNORE INTO memory_source_progress (source_session_id, time_bound, updated_at)
    SELECT session_id, last_memory_extraction_at, last_memory_extraction_at
    FROM sessions WHERE last_memory_extraction_at IS NOT NULL
"""
_DROP_READ_POINT_SQL = "ALTER TABLE sessions DROP COLUMN last_memory_extraction_at"
_OBSERVATIONS_TABLE = "memory_observations"
_SESSIONS_TABLE = "sessions"
_EXTRACTION_ID_COLUMN = "extraction_id"
_READ_POINT_COLUMN = "last_memory_extraction_at"


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    async with db.execute(_COLUMNS_SQL.format(table=table)) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def up(db: aiosqlite.Connection) -> None:
    """Create the memory extraction tables, seed per-source progress from the read points, drop the read point."""
    await db.execute(_BEGIN_SQL)
    try:
        for statement in _CREATE_TABLES_SQL:
            await db.execute(statement)
        async with db.execute(_TABLE_EXISTS_SQL, (_OBSERVATIONS_TABLE,)) as cursor:
            has_observations = await cursor.fetchone() is not None
        if has_observations and _EXTRACTION_ID_COLUMN not in await _columns(db, _OBSERVATIONS_TABLE):
            await db.execute(_ADD_EXTRACTION_ID_SQL)
        if has_observations:
            await db.execute(_EXTRACTION_ID_INDEX_SQL)
        if _READ_POINT_COLUMN in await _columns(db, _SESSIONS_TABLE):
            await db.execute(_SEED_PROGRESS_SQL)
            await db.execute(_DROP_READ_POINT_SQL)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
