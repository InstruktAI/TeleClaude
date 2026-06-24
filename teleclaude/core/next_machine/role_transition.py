"""Claim-gated in-place promotion of a slug's work-orchestrator claim-holder.

A substantive work-entry drift bounce must re-derive the affected prepare
artifact, which requires prepare-write authority. The session that bounced out of
``telec todo work`` holds the slug's ``active_runner`` claim, so spawning a fresh
prepare driver would conflict on that claim. Promoting the claim-holder in place
keeps one session and one claim: the session's ``job`` transitions from
``work-orchestrator`` to ``prepare-orchestrator``, the claim is untouched, and the
next artifact write satisfies the prepare write-authority guard.

The transition is the prepare-write trust boundary, so it is gated: only the live
``active_runner`` that currently holds ``job=work-orchestrator`` may be promoted,
and a granted promotion is recorded with a structured audit log line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import JobRole

if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


async def promote_work_orchestrator_to_prepare(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    session_id: str,
) -> bool:
    """Promote the slug's live claim-holder from work- to prepare-orchestrator.

    Asserts the caller IS the live ``active_runner`` for the slug AND currently
    holds ``job=work-orchestrator``, then mutates that session's ``job`` to
    ``prepare-orchestrator`` and emits one structured audit log line. Returns
    ``True`` on a granted promotion, ``False`` (with no mutation) when either gate
    fails.
    """
    state = await todos_db.read_state(slug)
    active_runner = state.get("active_runner") if state is not None else None
    if not isinstance(active_runner, str) or active_runner != session_id:
        logger.warning(
            "role_promotion_refused slug=%s session_id=%s reason=not_active_runner active_runner=%s",
            slug,
            session_id,
            active_runner,
        )
        return False
    session = await db.get_session(session_id)
    if session is None or session.job != JobRole.WORK_ORCHESTRATOR.value:
        current_job = session.job if session is not None else None
        logger.warning(
            "role_promotion_refused slug=%s session_id=%s reason=not_work_orchestrator job=%s",
            slug,
            session_id,
            current_job,
        )
        return False
    await db.update_session(session_id, job=JobRole.PREPARE_ORCHESTRATOR.value)
    logger.info(
        "role_promotion_granted slug=%s session_id=%s from_job=%s to_job=%s",
        slug,
        session_id,
        JobRole.WORK_ORCHESTRATOR.value,
        JobRole.PREPARE_ORCHESTRATOR.value,
    )
    return True


__all__ = ["promote_work_orchestrator_to_prepare"]
