"""Prune non-canonical mirrors created before transcript allowlisting."""

from __future__ import annotations

import json
import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript_discovery import in_session_root

logger = get_logger(__name__)


async def up(db: aiosqlite.Connection) -> None:
    """Delete mirror rows that point at non-canonical transcript paths."""
    db.row_factory = aiosqlite.Row
    try:
        rows = await (await db.execute("SELECT id, agent, metadata FROM mirrors")).fetchall()
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return
        raise

    to_delete: list[int] = []
    for row in rows:
        metadata_raw = row["metadata"]
        try:
            metadata = json.loads(metadata_raw or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue

        transcript_path = metadata.get("transcript_path")
        agent_value = metadata.get("agent") or row["agent"]
        if not isinstance(transcript_path, str) or not transcript_path:
            continue
        if not isinstance(agent_value, str):
            continue
        try:
            agent = AgentName(agent_value)
        except ValueError:
            continue

        if not in_session_root(transcript_path, agent):
            to_delete.append(int(row["id"]))

    for row_id in to_delete:
        await db.execute("DELETE FROM mirrors WHERE id = ?", (row_id,))

    if to_delete:
        await db.commit()

    logger.info("Pruned %d non-canonical mirror rows", len(to_delete))
