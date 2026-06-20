"""Receipt-backed todo removal — thin adapter onto the shared soft-remove primitive."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)


async def execute_todo_remove(db: Db, slug: str | None, cwd: str) -> str:
    """Soft-remove a todo via the shared DB primitive.

    Follows the standard engine entry contract ``(db, slug, cwd) -> str``. The
    ``db`` parameter is the daemon DB (unused — TodosDb is resolved from
    ``cwd``). The soft-remove primitive owns the full cascade: tombstone +
    dependency scrub + slug-keyed filesystem teardown.
    """

    if not slug:
        raise ValueError("slug is required for remove")

    todos_db = await get_todos_db(cwd)
    removed = await todos_db.soft_remove_from_todo(slug, cwd=cwd)
    if not removed:
        raise LookupError(f"no live todo found for remove: {slug}")
    logger.info("Removed todo %s", slug)
    return f"removed {slug}"
