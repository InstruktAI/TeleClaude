"""Rename terminal/rest outbox tables to api_outbox."""

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Rename legacy outbox tables + indexes to api_outbox."""
    renamed = False
    for legacy_table in ("terminal_outbox", "rest_outbox"):
        try:
            await db.execute(f"ALTER TABLE {legacy_table} RENAME TO api_outbox")
            renamed = True
            logger.info("Renamed %s to api_outbox", legacy_table)
            break
        except Exception as exc:  # table may not exist on fresh installs
            logger.info("Skip %s rename: %s", legacy_table, exc)

    if not renamed:
        logger.info("No legacy outbox table found to rename")

    await db.execute("DROP INDEX IF EXISTS idx_api_outbox_pending")
    await db.execute("DROP INDEX IF EXISTS idx_api_outbox_request")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_api_outbox_pending ON api_outbox(delivered_at, next_attempt_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_api_outbox_request ON api_outbox(request_id)")
