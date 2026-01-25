"""Add lifecycle_status column to sessions table."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations.constants import COLUMN_LIFECYCLE_STATUS

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Add lifecycle_status column with default 'active'."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns: set[str] = set()
    for row in rows:
        col_name = cast(str, row[1])
        existing_columns.add(col_name)

    if COLUMN_LIFECYCLE_STATUS not in existing_columns:
        await db.execute(f"ALTER TABLE sessions ADD COLUMN {COLUMN_LIFECYCLE_STATUS} TEXT DEFAULT 'active'")
        await db.commit()
        logger.info("Added lifecycle_status column to sessions table")
