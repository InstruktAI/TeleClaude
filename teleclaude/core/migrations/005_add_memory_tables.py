"""Add memory tables for observations, summaries, and manual sessions."""
# pylint: disable=invalid-name  # Migration filenames are versioned on purpose.


from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations._memory_sql import (
    build_memory_observations_table_sql,
    create_memory_observations_indexes,
    ensure_memory_observations_fts,
)

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - create memory tables and FTS5 index."""
    await db.execute(
        build_memory_observations_table_sql(
            table_name="memory_observations",
            type_sql="TEXT NOT NULL CHECK(type IN ('decision','bugfix','feature','refactor','discovery','change'))",
        )
    )
    await create_memory_observations_indexes(db)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS memory_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            created_at TEXT NOT NULL,
            created_at_epoch INTEGER NOT NULL
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_sum_project ON memory_summaries(project, created_at_epoch DESC)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_sum_session ON memory_summaries(memory_session_id)")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS memory_manual_sessions (
            memory_session_id TEXT PRIMARY KEY,
            project TEXT UNIQUE NOT NULL,
            created_at_epoch INTEGER NOT NULL
        )
    """)

    # FTS5 for full-text search on observations
    await ensure_memory_observations_fts(db, logger)

    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """Revert migration."""
