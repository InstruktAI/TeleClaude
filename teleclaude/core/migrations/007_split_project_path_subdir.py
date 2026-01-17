"""Split combined worktree paths into project_path + subdir."""

# mypy: disable-error-code="misc"
# Migration files handle untyped sqlite rows

from __future__ import annotations

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Split worktree project_path into project_path + subdir."""
    cursor = await db.execute("PRAGMA table_info(sessions)")
    columns: set[str] = {str(row[1]) for row in await cursor.fetchall()}
    if "project_path" not in columns or "subdir" not in columns:
        logger.info("Skipping worktree split migration: columns missing")
        return

    await db.execute(
        """
        UPDATE sessions
        SET
            subdir = substr(project_path, instr(project_path, '/trees/') + 1),
            project_path = substr(project_path, 1, instr(project_path, '/trees/') - 1)
        WHERE
            project_path LIKE '%/trees/%'
            AND instr(project_path, '/trees/') > 0
            AND (subdir IS NULL OR subdir = '')
        """
    )
    await db.commit()
    logger.info("Split project_path and subdir for worktree sessions")
