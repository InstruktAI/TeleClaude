"""Drop legacy api_outbox table and indexes."""

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Drop api_outbox table + indexes if present."""
    await db.execute("DROP INDEX IF EXISTS idx_api_outbox_pending")
    await db.execute("DROP INDEX IF EXISTS idx_api_outbox_request")
    await db.execute("DROP TABLE IF EXISTS api_outbox")
    logger.info("Dropped api_outbox table (if present)")
