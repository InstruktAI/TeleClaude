"""Add working_slug column to sessions table for state machine tracking."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Add working_slug column if it doesn't exist."""
    # Get current columns
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns: set[str] = set()
    for row in rows:
        col_name = cast(str, row[1])
        existing_columns.add(col_name)

    # Add working_slug if missing
    if "working_slug" not in existing_columns:
        await db.execute("ALTER TABLE sessions ADD COLUMN working_slug TEXT")
        await db.commit()
        logger.info("Added working_slug column to sessions table")
