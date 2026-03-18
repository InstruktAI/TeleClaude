"""Shared SQL helpers for memory-related migrations."""

from __future__ import annotations

from logging import Logger

import aiosqlite


def build_memory_observations_table_sql(*, table_name: str, type_sql: str) -> str:
    """Return CREATE TABLE SQL for a memory observations table variant."""
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            type {type_sql},
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
    """


async def create_memory_observations_indexes(db: aiosqlite.Connection) -> None:
    """Create indexes for the canonical memory_observations table."""
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type)")


async def ensure_memory_observations_fts(
    db: aiosqlite.Connection,
    logger: Logger,
    *,
    rebuild: bool = False,
) -> None:
    """Create or rebuild the FTS index and its triggers for memory_observations."""
    try:
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_observations_fts USING fts5(
                title, subtitle, narrative, facts, concepts,
                content='memory_observations',
                content_rowid='id'
            )
        """)
        if rebuild:
            await db.execute("""
                INSERT INTO memory_observations_fts(memory_observations_fts) VALUES('rebuild')
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
    except aiosqlite.Error:
        logger.warning("FTS5 not available; memory search will use LIKE fallback")
