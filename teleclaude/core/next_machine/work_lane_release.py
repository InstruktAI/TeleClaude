"""Return a todo from the work lane to preparation.

The workflow context owns the rule "returning work to preparation releases the work
lane": the work orchestrator's claim is released, every session it started is ended
on whichever computer it runs, and only then the orchestrator itself. Session
termination stays owned by ``agent_runtime``; this module crosses to it through its
published ``CloseSessionCommand`` under the daemon principal. The worktree, branches,
workspace and build commits are never touched.

The release is idempotent: a repeated release changes no claim and re-requests the
close only of sessions that are still open. The orchestrator's own close is requested
only when no session it started remains open; a child that does not end withholds it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import Db
from teleclaude.core.next_machine.unclaim import ClaimReleaseStatus, unclaim_todo_for_caller
from teleclaude.core.operation_follow_through import FollowThrough
from teleclaude.types.commands import CloseSessionCommand

logger = get_logger(__name__)

_RELEASED_EVENT = "work_lane_released"
_RELEASED_MESSAGE = "work lane returned to preparation"
_CLAIM_REFUSED_EVENT = "work_lane_release_claim_refused"
_CLAIM_REFUSED_MESSAGE = "work lane release refused: the claim was not released, no session was ended"
_CHILD_RESIDUAL_EVENT = "work_lane_release_child_open"
_CHILD_RESIDUAL_MESSAGE = "work lane release incomplete: a session the orchestrator started is still open"
_ORCHESTRATOR_WITHHELD_EVENT = "work_lane_release_orchestrator_withheld"
_ORCHESTRATOR_WITHHELD_MESSAGE = "work lane release incomplete: the orchestrator's close is withheld"
_CLOSE_FAILED_EVENT = "work_lane_release_close_failed"
_CLOSE_FAILED_MESSAGE = "work lane release could not dispatch a session close"

# Convergence on the children having actually ended: a close request returns a receipt
# (acceptance, not termination), so the enumeration is re-read until it is empty.
_CONVERGENCE_DEADLINE_S = 30.0
_CONVERGENCE_POLL_INTERVAL_S = 0.25


class WorkLaneReturnReason(StrEnum):
    """Why a todo returns from the work lane to preparation."""

    KICKBACK = "kickback"
    SUBSTANTIVE_DRIFT = "substantive_drift"


@dataclass(frozen=True)
class _OpenSession:
    """A session still open, with the computer that owns it (``None`` for this one)."""

    session_id: str
    computer: str | None


@dataclass(frozen=True)
class WorkLaneRelease:
    """What one release did, for the single completion record."""

    claim_released: bool
    close_requested: tuple[str, ...]
    ended: tuple[str, ...]
    residual: tuple[_OpenSession, ...]
    orchestrator_close_requested: bool


async def _open_children(db: Db, orchestrator_session_id: str) -> list[_OpenSession]:
    """Every open session the orchestrator started, on this computer or another.

    The local registry is authoritative for this computer's sessions and includes those
    still initializing or headless. Other computers' sessions come from the daemon cache.
    """
    local = await db.list_sessions(all_open=True, initiator_session_id=orchestrator_session_id)
    children = {session.session_id: _OpenSession(session.session_id, None) for session in local}
    cache = get_command_service().client.cache
    if cache is None:
        return list(children.values())
    local_computer = config.computer.name
    for snapshot in cache.get_sessions():
        if (
            snapshot.initiator_session_id == orchestrator_session_id
            and snapshot.closed_at is None
            and snapshot.computer not in (None, local_computer)
            and snapshot.session_id not in children
        ):
            children[snapshot.session_id] = _OpenSession(snapshot.session_id, snapshot.computer)
    return list(children.values())


async def _request_close(session: _OpenSession) -> bool:
    """Ask the owning computer to end one session; ``False`` when the request could not be dispatched."""
    command = CloseSessionCommand(session_id=session.session_id)
    command.computer = session.computer
    try:
        await dispatch_command(get_command_service().client, command, principal=SYSTEM_DAEMON_PRINCIPAL)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error(
            _CLOSE_FAILED_MESSAGE,
            event=_CLOSE_FAILED_EVENT,
            session_id=session.session_id,
            computer=session.computer,
            error=str(exc),
        )
        return False
    return True


async def _end_children(db: Db, orchestrator_session_id: str) -> tuple[set[str], list[_OpenSession]]:
    """Request the close of every child and wait until none is open.

    Returns the ids whose close was requested and the children still open when the
    wait gave up (a close that failed to dispatch, or the deadline).
    """
    requested: set[str] = set()
    deadline = time.monotonic() + _CONVERGENCE_DEADLINE_S
    while True:
        open_children = await _open_children(db, orchestrator_session_id)
        if not open_children:
            return requested, []
        if time.monotonic() >= deadline:
            return requested, open_children
        accepted = [await _request_close(child) for child in open_children]
        requested.update(child.session_id for child, ok in zip(open_children, accepted, strict=True) if ok)
        if not all(accepted):
            return requested, await _open_children(db, orchestrator_session_id)
        await asyncio.sleep(_CONVERGENCE_POLL_INTERVAL_S)


async def return_work_to_preparation(
    db: Db,
    *,
    slug: str,
    project_root: str,
    orchestrator_session_id: str,
    reason: WorkLaneReturnReason,
) -> WorkLaneRelease:
    """Release the claim, end the sessions the orchestrator started, then end the orchestrator.

    The claim is released first, so the lifecycle runner can dispatch the next lane even
    if a close fails. A release that cannot release the claim ends nothing.
    """
    claim = await unclaim_todo_for_caller(
        db,
        slug=slug,
        cwd=project_root,
        caller_session_id=orchestrator_session_id,
    )
    if claim.status is ClaimReleaseStatus.REFUSED:
        logger.error(
            _CLAIM_REFUSED_MESSAGE,
            event=_CLAIM_REFUSED_EVENT,
            slug=slug,
            reason=reason.value,
            orchestrator_session_id=orchestrator_session_id,
            refusal_reason=claim.refusal_reason.value if claim.refusal_reason else None,
        )
        return WorkLaneRelease(
            claim_released=False,
            close_requested=(),
            ended=(),
            residual=(),
            orchestrator_close_requested=False,
        )

    requested, residual = await _end_children(db, orchestrator_session_id)
    for child in residual:
        logger.error(
            _CHILD_RESIDUAL_MESSAGE,
            event=_CHILD_RESIDUAL_EVENT,
            slug=slug,
            orchestrator_session_id=orchestrator_session_id,
            session_id=child.session_id,
            computer=child.computer,
        )

    orchestrator_close_requested = False
    if residual:
        logger.error(
            _ORCHESTRATOR_WITHHELD_MESSAGE,
            event=_ORCHESTRATOR_WITHHELD_EVENT,
            slug=slug,
            orchestrator_session_id=orchestrator_session_id,
            computer=config.computer.name,
        )
    else:
        orchestrator_close_requested = await _request_close(_OpenSession(orchestrator_session_id, None))

    residual_ids = {child.session_id for child in residual}
    release = WorkLaneRelease(
        claim_released=claim.status is ClaimReleaseStatus.RELEASED,
        close_requested=tuple(sorted(requested)),
        ended=tuple(sorted(requested - residual_ids)),
        residual=tuple(residual),
        orchestrator_close_requested=orchestrator_close_requested,
    )
    logger.info(
        _RELEASED_MESSAGE,
        event=_RELEASED_EVENT,
        slug=slug,
        reason=reason.value,
        orchestrator_session_id=orchestrator_session_id,
        claim_released=release.claim_released,
        close_requested=release.close_requested,
        ended=release.ended,
        orchestrator_close_requested=release.orchestrator_close_requested,
    )
    return release


def work_lane_return_follow_through(
    db: Db,
    *,
    slug: str,
    project_root: str,
    orchestrator_session_id: str,
    reason: WorkLaneReturnReason,
) -> FollowThrough:
    """Bind one release as a deferred follow-through, run after the triggering call has answered."""

    async def follow_through() -> object:
        return await return_work_to_preparation(
            db,
            slug=slug,
            project_root=project_root,
            orchestrator_session_id=orchestrator_session_id,
            reason=reason,
        )

    return follow_through


__all__ = [
    "WorkLaneRelease",
    "WorkLaneReturnReason",
    "return_work_to_preparation",
    "work_lane_return_follow_through",
]
