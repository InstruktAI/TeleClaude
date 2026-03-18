"""Widen memory_observations type CHECK constraint for relationship-centric types.

Replaces activity-tracking types (bugfix, feature, refactor, change) with
relationship-centric types (preference, gotcha, pattern, friction, context).
Keeps: decision, discovery. App-layer enum is the source of truth.
"""
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
    """Recreate memory_observations without CHECK constraint on type."""
    # Drop FTS triggers first
    for trigger in ("memory_obs_ai", "memory_obs_ad", "memory_obs_au"):
        await db.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    # Drop FTS table
    await db.execute("DROP TABLE IF EXISTS memory_observations_fts")

    # Create new table without CHECK constraint (validated at app layer)
    await db.execute(
        build_memory_observations_table_sql(
            table_name="memory_observations_new",
            type_sql="TEXT NOT NULL",
        )
    )

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
    await create_memory_observations_indexes(db)

    # Recreate FTS5
    await ensure_memory_observations_fts(db, logger, rebuild=True)

    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """Revert migration."""
