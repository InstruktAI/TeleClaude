"""Receipt-backed todo removal — thin adapter onto the shared soft-remove primitive."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.runtime.sessions import claim_is_held
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.todos_db._exceptions import RemoveRefusedLiveWork
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store

logger = get_logger(__name__)

_CALLER_BINDING_RELEASED_EVENT = "todo removal released caller binding"


async def _release_caller_binding_once_removed(
    db: Db, todos_db: WorkflowStore, slug: str, caller_session_id: str | None
) -> None:
    """Unbind the caller from ``slug`` once the slug no longer resolves to a live todo.

    Keyed on the committed todo state rather than on the removal call returning,
    so cleanup that fails or is cancelled after the tombstone lands still frees
    the caller, while a refused removal leaves the binding intact.
    """
    if caller_session_id is None:
        return
    caller = await db.get_session(caller_session_id)
    if caller is None or caller.working_slug != slug:
        return
    if await todos_db.read_state(slug) is not None:
        return
    await db.update_session(caller_session_id, working_slug=None)
    logger.info(_CALLER_BINDING_RELEASED_EVENT, slug=slug, session_id=caller_session_id)


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
    ``db`` parameter is the daemon DB (unused — WorkflowStore is resolved from
    ``cwd``). The soft-remove primitive owns the full cascade: tombstone +
    dependency scrub + slug-keyed filesystem teardown.
    """

    if not slug:
        raise ValueError("slug is required for remove")

    todos_db = await get_workflow_store(cwd)
    caller_session_id = get_caller_session_id()
    state = await todos_db.read_state(slug)
    raw_claim_holder = state.get("active_runner") if isinstance(state, dict) else None
    claim_holder = (
        raw_claim_holder
        if isinstance(raw_claim_holder, str)
        and raw_claim_holder != caller_session_id
        and await claim_is_held(db, cwd, slug, raw_claim_holder)
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

    try:
        removed = await todos_db.soft_remove_from_todo(
            slug,
            cwd=cwd,
            removal_context={
                "force": force,
                "operation_id": current_operation_id,
                "caller_session_id": caller_session_id,
            },
        )
    finally:
        await _release_caller_binding_once_removed(db, todos_db, slug, caller_session_id)
    if not removed:
        raise LookupError(f"no live todo found for remove: {slug}")
    logger.info("Removed todo %s", slug)
    return f"removed {slug}"
