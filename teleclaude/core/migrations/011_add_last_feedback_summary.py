"""Add last_feedback_summary column to sessions table.

This separates LLM-generated summaries from raw agent output.
Now last_feedback_received contains raw output and last_feedback_summary
contains the LLM summary. The summarizer.use_summary config determines
which field is used for display.
"""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations.constants import COLUMN_LAST_FEEDBACK_SUMMARY

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Add last_feedback_summary column if it doesn't exist."""
    # Get current columns
    cursor = await db.execute("PRAGMA table_info(sessions)")
    rows = await cursor.fetchall()
    existing_columns: set[str] = set()
    for row in rows:
        col_name = cast(str, row[1])
        existing_columns.add(col_name)

    # Add last_feedback_summary if missing
    if COLUMN_LAST_FEEDBACK_SUMMARY not in existing_columns:
        await db.execute("ALTER TABLE sessions ADD COLUMN last_feedback_summary TEXT")
        await db.commit()
        logger.info("Added last_feedback_summary column to sessions table")
