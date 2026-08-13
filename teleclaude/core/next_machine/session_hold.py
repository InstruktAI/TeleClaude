"""Workflow state mutations driven by session lifecycle controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.dispatch_claims import release_dispatch_claims_for_session
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.session_listeners import notify_gate_approved
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.project_root import is_project_checkout, resolve_project_root
from teleclaude.types.todos import HoldAuditSource, HoldAuditState

logger = get_logger(__name__)

MANUAL_CLOSE_HELD_REASON = "held"
ACTIVE_RUNNER_CLEARED_REASON = "cleared"
_SESSION_NOT_PROJECT_CHECKOUT_REASON = "session-not-project-checkout"


@dataclass(frozen=True)
class ActiveRunnerMutationResult:
    slug: str | None
    project_path: str | None
    mutated: bool
    reason: str


@dataclass(frozen=True)
class DriverOwnershipReconciliation:
    """Claims released and todo driver links cleared for one terminal session."""

    released_claims: int
    cleared_slugs: tuple[str, ...]


def _workflow_project_path(session_project_path: str | None) -> tuple[str | None, str]:
    if not session_project_path:
        return None, "session-project-missing"
    project_path = str(Path(session_project_path).resolve())
    if not is_project_checkout(project_path):
        return None, _SESSION_NOT_PROJECT_CHECKOUT_REASON
    return project_path, "ok"


async def _emit_todo_updated(*, slug: str, project_path: str, source: str) -> None:
    try:
        await emit_event(
            event="workflow.todo.updated",
            source=source,
            level=EventLevel.WORKFLOW,
            domain="software-development",
            payload={
                "slug": slug,
                "project_path": project_path,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    except RuntimeError:
        logger.info("workflow.todo.updated not emitted: event producer unavailable", slug=slug)


async def _emit_session_ended(*, session_id: str, project_path: str) -> None:
    try:
        await emit_event(
            event="agent_runtime.session.ended",
            source="agent_runtime",
            level=EventLevel.WORKFLOW,
            domain="agent_runtime",
            payload={
                "session_id": session_id,
                "project_path": project_path,
                "ended_at": datetime.now(UTC).isoformat(),
            },
        )
    except RuntimeError:
        logger.info("agent_runtime.session.ended not emitted: event producer unavailable", session_id=session_id)


async def _active_runner_slug(db: Db, session_id: str) -> tuple[str | None, str | None, str]:
    session = await db.get_session(session_id)
    if session is None:
        return None, None, "session-not-found"
    project_path, reason = _workflow_project_path(session.project_path)
    if project_path is None:
        return None, None, reason
    todos_db = await get_todos_db(project_path)
    matches: list[str] = []
    for row in await todos_db.list_todo(include_icebox=True):
        state = await todos_db.read_state(row["slug"])
        if state and state.get("active_runner") == session_id:
            matches.append(row["slug"])
    if not matches:
        return None, project_path, "active-runner-not-found"
    if len(matches) > 1:
        return None, project_path, "active-runner-ambiguous"
    return matches[0], project_path, "ok"


async def _project_path_for_session_end(db: Db, session_id: str) -> tuple[str | None, str]:
    session = await db.get_session(session_id)
    if session is None:
        return None, "session-not-found"
    project_path, reason = _workflow_project_path(session.project_path)
    if project_path is None:
        return None, reason
    return project_path, "ok"


async def reconcile_driver_ownership_for_session(todos_db: TodosDb, session_id: str) -> DriverOwnershipReconciliation:
    """Release session-bound claims and clear every active driver link for a session."""
    released_claims = await release_dispatch_claims_for_session(todos_db, session_id=session_id)
    cleared_slugs: list[str] = []
    for row in await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True):
        state = await todos_db.read_state_by_id(row["id"])
        if state is None or state.get("active_runner") != session_id:
            continue
        writer = StateWriter(state)
        writer.state.active_runner = None
        writer.state.manually_started = False
        await writer.commit_by_id(todos_db, row["id"])
        cleared_slugs.append(row["slug"])
    return DriverOwnershipReconciliation(released_claims=released_claims, cleared_slugs=tuple(cleared_slugs))


def hold_todo_for_diagnosis_unresolved(writer: StateWriter, *, reason: str, caller_session_id: str) -> None:
    """Hold a todo whose dispatched diagnosis peer could not settle a cause.

    Unlike ``hold_todo_for_manual_session_close``, the caller — the stamp
    boundary in ``next_machine.stamps`` — already resolved the slug and loaded
    its state; there is no session/project lookup to redo here, only the same
    hold-brake shape every other hold source uses. No settled stamp is
    recorded, so ``_diagnosis_settled_current`` stays false and the diagnosis
    is never consumed as a conclusion. The hold itself is what stops a
    subsequent ``telec todo prepare`` call from re-deriving the same DIAGNOSE
    dispatch indefinitely; releasing it (``telec todo update <slug>
    --release``) returns the lane to DIAGNOSE for a fresh attempt.
    """
    writer.state.hold = True
    writer.state.hold_audit = HoldAuditState(
        source=HoldAuditSource.DIAGNOSIS_UNRESOLVED,
        set_at=datetime.now(UTC).isoformat(),
        set_by_session_id=caller_session_id,
        reason=reason,
    )


async def hold_todo_for_manual_session_close(db: Db, session_id: str) -> ActiveRunnerMutationResult:
    slug, project_path, reason = await _active_runner_slug(db, session_id)
    if slug is None or project_path is None:
        if reason != _SESSION_NOT_PROJECT_CHECKOUT_REASON:
            logger.warning(
                "manual session close could not correlate active_runner", session_id=session_id, reason=reason
            )
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason=reason)

    todos_db = await get_todos_db(project_path)
    state = await todos_db.read_state(slug)
    if state is None:
        return ActiveRunnerMutationResult(slug=slug, project_path=project_path, mutated=False, reason="state-not-found")
    writer = StateWriter(state)
    writer.state.hold = True
    writer.state.hold_audit = HoldAuditState(
        source=HoldAuditSource.SESSION_CLOSE,
        set_at=datetime.now(UTC).isoformat(),
        set_by_session_id=session_id,
        reason="manual session close",
    )
    await writer.commit(todos_db, slug)
    await _emit_todo_updated(slug=slug, project_path=project_path, source="workflow.session_close")
    return ActiveRunnerMutationResult(
        slug=slug,
        project_path=project_path,
        mutated=True,
        reason=MANUAL_CLOSE_HELD_REASON,
    )


async def clear_active_runner_for_session_end(db: Db, session_id: str) -> ActiveRunnerMutationResult:
    project_path, reason = await _project_path_for_session_end(db, session_id)
    if project_path is not None:
        await _emit_session_ended(session_id=session_id, project_path=project_path)
    if project_path is None:
        return ActiveRunnerMutationResult(slug=None, project_path=None, mutated=False, reason=reason)
    todos_db = await get_todos_db(project_path)
    reconciliation = await reconcile_driver_ownership_for_session(todos_db, session_id)
    if reconciliation.released_claims or reconciliation.cleared_slugs:
        logger.info(
            "session driver ownership reconciled",
            session_id=session_id,
            released_claims=reconciliation.released_claims,
            cleared_slugs=",".join(reconciliation.cleared_slugs),
        )
    if not reconciliation.cleared_slugs:
        return ActiveRunnerMutationResult(
            slug=None,
            project_path=project_path,
            mutated=bool(reconciliation.released_claims),
            reason=reason,
        )
    return ActiveRunnerMutationResult(
        slug=reconciliation.cleared_slugs[0],
        project_path=project_path,
        mutated=True,
        reason=ACTIVE_RUNNER_CLEARED_REASON,
    )


async def notify_runner_of_gate_approval(cwd: str, slug: str) -> bool:
    """Tell a parked runner session that the operator cleared its approval gate.

    Reads ``active_runner`` for the just-approved slug and delivers the operator
    notification into that session so it resumes. A no-op when no live runner is
    linked (the agent already exited).
    """
    todos_db = await get_todos_db(resolve_project_root(cwd))
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    active_runner = state.get("active_runner")
    if not isinstance(active_runner, str) or not active_runner:
        return False
    return await notify_gate_approved(active_runner, slug=slug)


__all__ = [
    "ACTIVE_RUNNER_CLEARED_REASON",
    "MANUAL_CLOSE_HELD_REASON",
    "ActiveRunnerMutationResult",
    "DriverOwnershipReconciliation",
    "clear_active_runner_for_session_end",
    "hold_todo_for_diagnosis_unresolved",
    "hold_todo_for_manual_session_close",
    "notify_runner_of_gate_approval",
    "reconcile_driver_ownership_for_session",
]
