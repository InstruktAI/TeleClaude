"""Rename terminal_outbox to rest_outbox."""

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Rename terminal_outbox table + indexes to rest_outbox."""
    try:
        await db.execute("ALTER TABLE terminal_outbox RENAME TO rest_outbox")
    except Exception as exc:  # table may not exist on fresh installs
        logger.info("Skip rest_outbox rename: %s", exc)

    await db.execute("DROP INDEX IF EXISTS idx_terminal_outbox_pending")
    await db.execute("DROP INDEX IF EXISTS idx_terminal_outbox_request")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_rest_outbox_pending ON rest_outbox(delivered_at, next_attempt_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_rest_outbox_request ON rest_outbox(request_id)")
