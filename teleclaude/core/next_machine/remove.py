"""Receipt-backed todo removal — thin adapter onto the shared soft-remove primitive."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.todos_db import get_todos_db
from teleclaude.core.todos_db._exceptions import RemoveRefusedLiveWork

logger = get_logger(__name__)


async def execute_todo_remove(
    db: Db,
    slug: str | None,
    cwd: str,
    *,
    force: bool = False,
    current_operation_id: str | None = None,
) -> str:
    """Soft-remove a todo via the shared DB primitive.

    Follows the standard engine entry contract ``(db, slug, cwd) -> str``. The
    ``db`` parameter is the daemon DB (unused — TodosDb is resolved from
    ``cwd``). The soft-remove primitive owns the full cascade: tombstone +
    dependency scrub + slug-keyed filesystem teardown.
    """

    if not slug:
        raise ValueError("slug is required for remove")

    todos_db = await get_todos_db(cwd)
    caller_session_id = get_caller_session_id()
    state = await todos_db.read_state(slug)
    raw_claim_holder = state.get("active_runner") if isinstance(state, dict) else None
    claim_holder = (
        raw_claim_holder
        if isinstance(raw_claim_holder, str)
        and raw_claim_holder != caller_session_id
        and await is_live_session_id(db, raw_claim_holder)
        else None
    )
    operations = await db.find_nonterminal_operations_bound_to_todo(
        old_slug=slug,
        cwd=cwd,
        exclude_operation_id=current_operation_id,
    )
    sessions = await db.find_open_sessions_bound_to_todo(
        old_slug=slug,
        cwd=cwd,
        exclude_session_id=caller_session_id,
    )
    session_ids = sorted({session.session_id for session in sessions})
    operation_ids = sorted({operation.operation_id for operation in operations})
    if claim_holder is not None or session_ids or operation_ids:
        if not force:
            logger.info(
                "todo removal refused for live work",
                slug=slug,
                operation_id=current_operation_id,
                claim_holder=claim_holder,
                session_ids=session_ids,
                operation_ids=operation_ids,
            )
            raise RemoveRefusedLiveWork(
                slug=slug,
                session_ids=session_ids,
                operation_ids=operation_ids,
                claim_holder=claim_holder,
            )
        logger.info(
            "todo removal overriding live work",
            slug=slug,
            operation_id=current_operation_id,
            claim_holder=claim_holder,
            session_ids=session_ids,
            operation_ids=operation_ids,
        )

    removed = await todos_db.soft_remove_from_todo(
        slug,
        cwd=cwd,
        removal_context={
            "force": force,
            "operation_id": current_operation_id,
            "caller_session_id": caller_session_id,
        },
    )
    if not removed:
        raise LookupError(f"no live todo found for remove: {slug}")
    logger.info("Removed todo %s", slug)
    return f"removed {slug}"
