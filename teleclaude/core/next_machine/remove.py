"""Receipt-backed todo removal — cascade delete + worktree cleanup."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)


async def execute_todo_remove(db: Db, slug: str | None, cwd: str) -> str:
    """Remove a todo: delete state, artifacts, roadmap entry, and clean up worktree.

    Follows the standard engine entry contract ``(db, slug, cwd) -> str``.
    The ``db`` parameter is the daemon DB (unused here — TodosDb is resolved from ``cwd``).
    """

    if not slug:
        return "error: slug is required for remove"

    todos_db = await get_todos_db(cwd)

    state = await todos_db.read_state(slug)
    is_draft = isinstance(state, dict) and state.get("kind") == "draft"

    async with todos_db._session() as session:
        async with session.begin():
            await todos_db.delete_state(slug, session=session)
            await todos_db.delete_artifacts(slug, session=session)
            await todos_db.remove_from_roadmap(slug, session=session)
            await todos_db.clean_dep_references(slug, session=session)

    todos_db.on_committed("todo_removed")

    if not is_draft:
        await asyncio.to_thread(cleanup_delivered_slug, cwd, slug)

    logger.info("Removed todo %s (draft=%s)", slug, is_draft)
    return f"removed {slug}"
