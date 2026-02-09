"""Widen memory_observations type CHECK constraint for relationship-centric types.

Replaces activity-tracking types (bugfix, feature, refactor, change) with
relationship-centric types (preference, gotcha, pattern, friction, context).
Keeps: decision, discovery. App-layer enum is the source of truth.
"""

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Recreate memory_observations without CHECK constraint on type."""
    # Drop FTS triggers first
    for trigger in ("memory_obs_ai", "memory_obs_ad", "memory_obs_au"):
        await db.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    # Drop FTS table
    await db.execute("DROP TABLE IF EXISTS memory_observations_fts")

    # Create new table without CHECK constraint (validated at app layer)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS memory_observations_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            type TEXT NOT NULL,
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

    # Copy data, mapping old types to new
    await db.execute("""
        INSERT INTO memory_observations_new
        SELECT id, memory_session_id, project,
            CASE type
                WHEN 'bugfix' THEN 'discovery'
                WHEN 'feature' THEN 'discovery'
                WHEN 'refactor' THEN 'discovery'
                WHEN 'change' THEN 'discovery'
                ELSE type
            END,
            title, subtitle, facts, narrative, concepts,
            files_read, files_modified, prompt_number, discovery_tokens,
            created_at, created_at_epoch
        FROM memory_observations
    """)

    await db.execute("DROP TABLE memory_observations")
    await db.execute("ALTER TABLE memory_observations_new RENAME TO memory_observations")

    # Recreate indexes
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC)"
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type)")

    # Recreate FTS5
    try:
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_observations_fts USING fts5(
                title, subtitle, narrative, facts, concepts,
                content='memory_observations',
                content_rowid='id'
            )
        """)

        # Rebuild FTS index from existing data
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
    except Exception:
        logger.warning("FTS5 not available; memory search will use LIKE fallback")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration."""
    pass
