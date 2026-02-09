"""Add memory tables for observations, summaries, and manual sessions."""

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - create memory tables and FTS5 index."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS memory_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('decision','bugfix','feature','refactor','discovery','change')),
            title TEXT,
            subtitle TEXT,
            facts TEXT,
            narrative TEXT,
            concepts TEXT,
            files_read TEXT,
            files_modified TEXT,
            prompt_number INTEGER,
            discovery_tokens INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            created_at_epoch INTEGER NOT NULL
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type)")

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
    try:
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_observations_fts USING fts5(
                title, subtitle, narrative, facts, concepts,
                content='memory_observations',
                content_rowid='id'
            )
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_obs_ai AFTER INSERT ON memory_observations BEGIN
                INSERT INTO memory_observations_fts(rowid, title, subtitle, narrative, facts, concepts)
                VALUES (new.id, new.title, new.subtitle, new.narrative, new.facts, new.concepts);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_obs_ad AFTER DELETE ON memory_observations BEGIN
                INSERT INTO memory_observations_fts(memory_observations_fts, rowid, title, subtitle, narrative, facts, concepts)
                VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.facts, old.concepts);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_obs_au AFTER UPDATE ON memory_observations BEGIN
                INSERT INTO memory_observations_fts(memory_observations_fts, rowid, title, subtitle, narrative, facts, concepts)
                VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.facts, old.concepts);
                INSERT INTO memory_observations_fts(rowid, title, subtitle, narrative, facts, concepts)
                VALUES (new.id, new.title, new.subtitle, new.narrative, new.facts, new.concepts);
            END
        """)
    except Exception:
        logger.warning("FTS5 not available; memory search will use LIKE fallback")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration."""
    pass
