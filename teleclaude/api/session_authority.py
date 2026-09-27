"""Refuse a caller act whose target is a session above it in the dispatch chain.

A dispatched session's completed turn already reaches the session that
dispatched it, so no session acts on a session above it — sending it a
message, opening or closing a direct conversation with it, unsubscribing from
it, ending it, or restarting it. The ancestry fact is
``session_descends_from`` (``teleclaude.core.session_utils``); this module is
its edge translation into an HTTP refusal, parallel to
``teleclaude.api.todo_artifact_authority`` for the todo-claim relationship —
that module reads a todo's claim, this one reads the session graph.
"""

from __future__ import annotations

from fastapi import HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.session_ownership import SessionLookup
from teleclaude.api.todo_artifact_authority import live_claim_holder
from teleclaude.constants import ROLE_WORKER
from teleclaude.core.session_utils import session_descends_from, session_in_claiming_group
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)

ACT_SEND_MESSAGE = "telec sessions send"
ACT_END = "telec sessions end"
ACT_UNSUBSCRIBE = "telec sessions unsubscribe"
ACT_RESTART = "telec sessions restart"
ACT_TAIL = "telec sessions tail"
_UNKNOWN_AUTHORITY_CONTEXT = "unknown"

_SESSION_ACT_REFUSED_ANCESTOR_EVENT = "session_act_refused_ancestor"
REFUSED_ANCESTOR_DETAIL = (
    "session '{target_session_id}' is above caller '{caller_session_id}' in its dispatch "
    "chain; {act} is refused. The caller's completed turn already reaches the session "
    "above it, so the result belongs in the caller's own output, not in an act directed "
    "upward."
)
_WORKER_TRANSCRIPT_READ_REFUSED_EVENT = "worker_transcript_read_refused"
_WORKER_TRANSCRIPT_READ_REFUSED_DETAIL = (
    "role 'worker' is not permitted to call {act}: workers read only transcripts of "
    "participants in todo '{slug}'. Ask dispatching session '{initiator_session_id}' "
    "for access."
)
_WORKER_TERMINAL_OBSERVATION_REFUSED_EVENT = "worker_terminal_observation_refused"
_WORKER_TERMINAL_OBSERVATION_REFUSED_DETAIL = (
    "role 'worker' is not permitted to call telec sessions tail --pane; "
    "terminal observation is outside the worker's reach."
)


async def refuse_act_on_ancestor(caller: CallerIdentity, target_session_id: str, act: str) -> None:
    """Refuse ``act`` when ``target_session_id`` is a strict ancestor of the caller.

    A caller with no session identity — a human at a terminal, the TUI — has
    no dispatch chain and is never refused. A caller targeting itself is not
    refused: identity is not descent. Called before any side effect of the
    act being attempted.
    """
    if not caller.session_id or caller.session_id == target_session_id:
        return
    if not await session_descends_from(caller.session_id, target_session_id):
        return
    logger.info(
        _SESSION_ACT_REFUSED_ANCESTOR_EVENT,
        caller_session_id=caller.session_id,
        target_session_id=target_session_id,
        act=act,
    )
    raise HTTPException(
        status_code=403,
        detail=REFUSED_ANCESTOR_DETAIL.format(
            target_session_id=target_session_id,
            caller_session_id=caller.session_id,
            act=act,
        ),
    )


async def refuse_worker_transcript_read_outside_todo(
    caller: CallerIdentity,
    target_session_id: str,
    *,
    session_db: SessionLookup,
) -> None:
    """Refuse a worker transcript read outside its live todo participants.

    The gate uses the worker session's project and working slug, the todo's
    live claim, and the local session dispatch graph. See command-clearance,
    "Claim-scoped transcript read".
    """
    if caller.system_role != ROLE_WORKER:
        return

    caller_session = await session_db.get_session(caller.session_id)
    working_slug = caller_session.working_slug if caller_session is not None else None
    project_path = caller_session.project_path if caller_session is not None else None
    holder = None
    if working_slug and project_path:
        todos_db = await get_todos_db(project_path)
        holder = await live_claim_holder(todos_db, working_slug)

    admitted = False
    if holder and await session_in_claiming_group(caller.session_id, holder):
        if target_session_id == holder:
            admitted = True
        elif await session_in_claiming_group(target_session_id, holder):
            target_session = await session_db.get_session(target_session_id)
            admitted = bool(
                target_session
                and target_session.working_slug == working_slug
                and target_session.project_path == project_path
            )
    if admitted:
        return

    initiator_session_id = caller_session.initiator_session_id if caller_session is not None else None
    logger.info(
        _WORKER_TRANSCRIPT_READ_REFUSED_EVENT,
        caller_session_id=caller.session_id,
        target_session_id=target_session_id,
        working_slug=working_slug,
        initiator_session_id=initiator_session_id,
    )
    raise HTTPException(
        status_code=403,
        detail=_WORKER_TRANSCRIPT_READ_REFUSED_DETAIL.format(
            act=ACT_TAIL,
            slug=working_slug or _UNKNOWN_AUTHORITY_CONTEXT,
            initiator_session_id=initiator_session_id or _UNKNOWN_AUTHORITY_CONTEXT,
        ),
    )


def admits_terminal_observation(caller: CallerIdentity) -> bool:
    """Return whether the caller may observe a live session terminal."""
    return caller.system_role != ROLE_WORKER


def refuse_worker_terminal_observation(caller: CallerIdentity) -> None:
    """Refuse explicit terminal observation for workers."""
    if admits_terminal_observation(caller):
        return
    logger.info(
        _WORKER_TERMINAL_OBSERVATION_REFUSED_EVENT,
        caller_session_id=caller.session_id,
    )
    raise HTTPException(status_code=403, detail=_WORKER_TERMINAL_OBSERVATION_REFUSED_DETAIL)
