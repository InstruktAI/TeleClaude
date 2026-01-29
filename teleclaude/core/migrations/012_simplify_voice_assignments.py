"""Simplify voice_assignments: drop per-service columns, rename voice_name to voice."""

# mypy: disable-error-code="misc"

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Recreate voice_assignments with simplified schema."""
    # Migrate data into new table, coalescing per-service columns into single voice field
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS voice_assignments_new (
            id TEXT PRIMARY KEY,
            service_name TEXT,
            voice TEXT DEFAULT '',
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO voice_assignments_new (id, service_name, voice, assigned_at)
        SELECT
            id,
            service_name,
            COALESCE(
                NULLIF(voice_name, ''),
                NULLIF(elevenlabs_id, ''),
                NULLIF(openai_voice, ''),
                NULLIF(macos_voice, ''),
                ''
            ),
            assigned_at
        FROM voice_assignments;

        DROP TABLE voice_assignments;

        ALTER TABLE voice_assignments_new RENAME TO voice_assignments;

        CREATE INDEX IF NOT EXISTS idx_voice_assignments_assigned_at ON voice_assignments(assigned_at);
    """)
    await db.commit()
    logger.info("Simplified voice_assignments table: dropped per-service columns, renamed voice_name to voice")
