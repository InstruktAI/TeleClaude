"""Add closed_at column to sessions table for soft-close tracking."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Add closed_at column if it doesn't exist."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns: set[str] = set()
    for row in rows:
        col_name = cast(str, row[1])
        existing_columns.add(col_name)

    if "closed_at" not in existing_columns:
        await db.execute("ALTER TABLE sessions ADD COLUMN closed_at TIMESTAMP")
        await db.commit()
        logger.info("Added closed_at column to sessions table")
