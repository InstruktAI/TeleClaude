"""Maintenance stage state machine stub for repo-wide upkeep."""

from __future__ import annotations

from teleclaude.core.db import Db


async def next_maintain(db: Db, cwd: str) -> str:  # noqa: ARG001
    """Maintenance state machine stub.

    Args:
        db: Database instance
        cwd: Project root

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    if not cwd:
        return "ERROR: No cwd provided to next_maintain."
    return "MAINTENANCE_EMPTY\n\nNo maintenance procedures are defined yet."
