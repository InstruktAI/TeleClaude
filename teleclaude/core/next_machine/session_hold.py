"""Workflow state mutations driven by session lifecycle controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine.driver_admission import schedule_claim_release
from teleclaude.core.next_machine.runtime.sessions import OwnSessionAnswer, is_github_backed, own_session_answer
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.session_listeners import notify_gate_approved
from teleclaude.core.session_runtime_gate import session_runtime_owner
from teleclaude.core.session_status import is_session_final
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.events.envelope import EventLevel
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import publish_event
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import TodoUpdated, TodoUpdatedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.project_root import is_project_checkout, resolve_project_root
from teleclaude.types.todos import HoldAuditSource, HoldAuditState

logger = get_logger(__name__)

MANUAL_CLOSE_HELD_REASON = "held"
ACTIVE_RUNNER_CLEARED_REASON = "cleared"
_GATE_APPROVAL_EVENT_SOURCE = "workflow.gate_approval"
_MANUAL_SESSION_CLOSE_DRIVER_CLASSIFIED_EVENT = "manual_session_close_driver_classified"
_SESSION_CLOSE_EVENT_SOURCE = "workflow.session_close"
_WORKFLOW_PROJECT_PATH_RESOLVED_REASON = "ok"
_ACTIVE_RUNNER_STATE_KEY = "active_runner"


class ManualCloseDriverReason(StrEnum):
    """Reasons produced by the manual-close driver correlation."""

    CURRENT_DRIVER = "current-driver"
    NON_DRIVER_WORKER = "non-driver-worker"
    RELEASED_DRIVER = "released-driver"
    ACTIVE_RUNNER_NOT_FOUND = "active-runner-not-found"
    ACTIVE_RUNNER_AMBIGUOUS = "active-runner-ambiguous"
    SESSION_NOT_FOUND = "session-not-found"
    SESSION_PROJECT_MISSING = "session-project-missing"
    SESSION_NOT_PROJECT_CHECKOUT = "session-not-project-checkout"
    STATE_NOT_FOUND = "state-not-found"


class ManualCloseDriverOutcome(StrEnum):
    """Terminal manual-close outcomes emitted for driver correlation."""

    HELD = "held"
    EXPLAINED_NOOP = "explained_noop"
    UNRESOLVED = "unresolved"


_SESSION_NOT_PROJECT_CHECKOUT_REASON = ManualCloseDriverReason.SESSION_NOT_PROJECT_CHECKOUT


@dataclass(frozen=True)
class ActiveRunnerMutationResult:
    slug: str | None
    project_path: str | None
    mutated: bool
    reason: str


@dataclass(frozen=True)
class DriverOwnershipReconciliation:
    """Todo driver links cleared for one terminal session."""

    cleared_slugs: tuple[str, ...]


@dataclass(frozen=True)
class ManualCloseDriverCorrelation:
    """The auditable driver relationship for one manual session close."""

    slug: str | None
    project_path: str | None
    reason: ManualCloseDriverReason


def _workflow_project_path(session_project_path: str | None) -> tuple[str | None, str]:
    if not session_project_path:
        return None, ManualCloseDriverReason.SESSION_PROJECT_MISSING
    project_path = str(Path(session_project_path).resolve())
    if not is_project_checkout(project_path):
        return None, _SESSION_NOT_PROJECT_CHECKOUT_REASON
    return project_path, _WORKFLOW_PROJECT_PATH_RESOLVED_REASON


async def emit_todo_updated(*, slug: str, project_root: str, source: str) -> None:
    try:
        await publish_event(
            TodoUpdated(
                subject=TodoRef(slug),
                home=home_for_project_path(project_root),
                data=TodoUpdatedData(slug=slug, project_path=project_root, updated_at=datetime.now(UTC).isoformat()),
            ),
            LegacyFacts(producer=source, level=EventLevel.WORKFLOW, domain="sdlc"),
        )
    except RuntimeError:
        logger.info("sdlc.todo.updated not emitted: event producer unavailable", slug=slug)


async def _manual_close_driver_correlation(db: Db, session_id: str) -> ManualCloseDriverCorrelation:
    session = await db.get_session(session_id)
    if session is None:
        return ManualCloseDriverCorrelation(
            slug=None,
            project_path=None,
            reason=ManualCloseDriverReason.SESSION_NOT_FOUND,
        )
    project_path, reason = _workflow_project_path(session.project_path)
    if project_path is None:
        return ManualCloseDriverCorrelation(
            slug=None,
            project_path=None,
            reason=ManualCloseDriverReason(reason),
        )
    todos_db = await get_workflow_store(project_path)
    matches: list[str] = []
    for row in await todos_db.list_todo(include_icebox=True):
        state = await todos_db.read_state(row["slug"])
        if state and state.get("active_runner") == session_id:
            matches.append(row["slug"])
    if len(matches) == 1:
        return ManualCloseDriverCorrelation(
            slug=matches[0],
            project_path=project_path,
            reason=ManualCloseDriverReason.CURRENT_DRIVER,
        )
    if len(matches) > 1:
        return ManualCloseDriverCorrelation(
            slug=None,
            project_path=project_path,
            reason=ManualCloseDriverReason.ACTIVE_RUNNER_AMBIGUOUS,
        )
    working_slug = session.working_slug
    if working_slug:
        state = await todos_db.read_state(working_slug)
        active_runner = state.get("active_runner") if state is not None else None
        if isinstance(active_runner, str) and active_runner:
            return ManualCloseDriverCorrelation(
                slug=working_slug,
                project_path=project_path,
                reason=ManualCloseDriverReason.NON_DRIVER_WORKER,
            )
        if await todos_db.removed_todo_claims_active_runner(working_slug, session_id):
            return ManualCloseDriverCorrelation(
                slug=working_slug,
                project_path=project_path,
                reason=ManualCloseDriverReason.RELEASED_DRIVER,
            )
    return ManualCloseDriverCorrelation(
        slug=None,
        project_path=project_path,
        reason=ManualCloseDriverReason.ACTIVE_RUNNER_NOT_FOUND,
    )


def _manual_close_driver_outcome(reason: ManualCloseDriverReason) -> ManualCloseDriverOutcome:
    if reason is ManualCloseDriverReason.CURRENT_DRIVER:
        return ManualCloseDriverOutcome.HELD
    if reason in {ManualCloseDriverReason.NON_DRIVER_WORKER, ManualCloseDriverReason.RELEASED_DRIVER}:
        return ManualCloseDriverOutcome.EXPLAINED_NOOP
    return ManualCloseDriverOutcome.UNRESOLVED


def _log_manual_close_driver_correlation(*, session_id: str, correlation: ManualCloseDriverCorrelation) -> None:
    outcome = _manual_close_driver_outcome(correlation.reason)
    log = logger.warning if outcome is ManualCloseDriverOutcome.UNRESOLVED else logger.info
    log(
        _MANUAL_SESSION_CLOSE_DRIVER_CLASSIFIED_EVENT,
        session_id=session_id,
        todo_slug=correlation.slug,
        outcome=outcome.value,
        reason=correlation.reason.value,
    )


async def _project_path_for_session_end(db: Db, session_id: str) -> tuple[str | None, str]:
    session = await db.get_session(session_id)
    if session is None:
        return None, "session-not-found"
    return _workflow_project_path(session.project_path)


async def reconcile_driver_ownership_for_session(
    todos_db: WorkflowStore, session_id: str
) -> DriverOwnershipReconciliation:
    """Clear every active driver link for a terminal session.

    A claim on a GitHub-backed project is written only on the master, so each todo the session still
    claims gets a release request instead, one per todo, issued without waiting for the master's answer;
    its ``cleared_slugs`` names the todos a release was requested for.
    """
    rows = await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True)
    if is_github_backed(todos_db.project_root):
        states = await todos_db.read_status_and_states_by_id([row["id"] for row in rows])
        claimed = sorted(
            {
                row["slug"]
                for row in rows
                if (state := states.get(row["id"])) is not None
                and state.state is not None
                and state.state.get(_ACTIVE_RUNNER_STATE_KEY) == session_id
            }
        )
        for slug in claimed:
            schedule_claim_release(todos_db.project_root, slug, session_id)
        return DriverOwnershipReconciliation(cleared_slugs=tuple(claimed))
    cleared_slugs: list[str] = []
    for row in rows:
        if await StateWriter.clear_active_runner_if_matches(todos_db, row["id"], session_id):
            cleared_slugs.append(row["slug"])
    return DriverOwnershipReconciliation(cleared_slugs=tuple(cleared_slugs))


async def _release_ended_github_claims(runtime_db: Db, project_root: Path, claims: dict[str, str]) -> None:
    """Request the release of each GitHub-backed claim whose session this computer shows ended.

    A claim for a session this computer never ran is left alone: its absence here says nothing about the
    computer that runs it, and the master judges it.
    """
    for slug, session_id in sorted(claims.items()):
        if await own_session_answer(runtime_db, project_root, slug, session_id) is not OwnSessionAnswer.ENDED:
            continue
        async with session_runtime_owner(session_id, wait=True):
            if await own_session_answer(runtime_db, project_root, slug, session_id) is OwnSessionAnswer.ENDED:
                schedule_claim_release(project_root, slug, session_id)


async def reconcile_terminal_driver_ownership(runtime_db: Db, project_path: str) -> None:
    """Recover terminal driver links from workflow references without dispatching work.

    On a GitHub-backed project only claims whose session this computer reports ended are released, and
    each release is requested of the master rather than written here.
    """
    todos_db = await get_workflow_store(project_path)
    rows = await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True)
    states = await todos_db.read_status_and_states_by_id([row["id"] for row in rows])
    if is_github_backed(project_path):
        claims = {
            row["slug"]: runner
            for row in rows
            if (read := states.get(row["id"])) is not None
            and read.state is not None
            and isinstance(runner := read.state.get(_ACTIVE_RUNNER_STATE_KEY), str)
            and runner
        }
        await _release_ended_github_claims(runtime_db, Path(project_path), claims)
        return
    identities: set[str] = set()
    for state in states.values():
        runner = state.state.get(_ACTIVE_RUNNER_STATE_KEY) if state.state is not None else None
        if isinstance(runner, str) and runner:
            identities.add(runner)
    for session_id in sorted(identities):
        current = await runtime_db.get_session(session_id)
        if current is not None and not (
            current.deleted_at
            or is_session_final(lifecycle_status=current.lifecycle_status, closed_at=current.closed_at)
        ):
            continue
        async with session_runtime_owner(session_id, wait=True):
            current = await runtime_db.get_session(session_id)
            if current is not None and not (
                current.deleted_at
                or is_session_final(lifecycle_status=current.lifecycle_status, closed_at=current.closed_at)
            ):
                continue
            await reconcile_driver_ownership_for_session(todos_db, session_id)


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
    correlation = await _manual_close_driver_correlation(db, session_id)
    if correlation.reason is not ManualCloseDriverReason.CURRENT_DRIVER:
        if correlation.reason is not _SESSION_NOT_PROJECT_CHECKOUT_REASON:
            _log_manual_close_driver_correlation(session_id=session_id, correlation=correlation)
        return ActiveRunnerMutationResult(
            slug=correlation.slug,
            project_path=correlation.project_path,
            mutated=False,
            reason=correlation.reason,
        )

    assert correlation.slug is not None and correlation.project_path is not None
    todos_db = await get_workflow_store(correlation.project_path)
    state = await todos_db.read_state(correlation.slug)
    if state is None:
        state_missing = ManualCloseDriverCorrelation(
            slug=correlation.slug,
            project_path=correlation.project_path,
            reason=ManualCloseDriverReason.STATE_NOT_FOUND,
        )
        _log_manual_close_driver_correlation(session_id=session_id, correlation=state_missing)
        return ActiveRunnerMutationResult(
            slug=correlation.slug,
            project_path=correlation.project_path,
            mutated=False,
            reason=state_missing.reason,
        )
    writer = StateWriter(state)
    writer.state.hold = True
    writer.state.hold_audit = HoldAuditState(
        source=HoldAuditSource.SESSION_CLOSE,
        set_at=datetime.now(UTC).isoformat(),
        set_by_session_id=session_id,
        reason="manual session close",
    )
    await writer.commit(todos_db, correlation.slug)
    _log_manual_close_driver_correlation(session_id=session_id, correlation=correlation)
    await emit_todo_updated(
        slug=correlation.slug,
        project_root=correlation.project_path,
        source=_SESSION_CLOSE_EVENT_SOURCE,
    )
    return ActiveRunnerMutationResult(
        slug=correlation.slug,
        project_path=correlation.project_path,
        mutated=True,
        reason=MANUAL_CLOSE_HELD_REASON,
    )


async def clear_active_runner_for_session_end(db: Db, session_id: str) -> ActiveRunnerMutationResult:
    project_path, reason = await _project_path_for_session_end(db, session_id)
    if project_path is None:
        return ActiveRunnerMutationResult(slug=None, project_path=None, mutated=False, reason=reason)
    todos_db = await get_workflow_store(project_path)
    reconciliation = await reconcile_driver_ownership_for_session(todos_db, session_id)
    if reconciliation.cleared_slugs:
        logger.info(
            "session driver ownership reconciled",
            session_id=session_id,
            cleared_slugs=",".join(reconciliation.cleared_slugs),
        )
    if not reconciliation.cleared_slugs:
        return ActiveRunnerMutationResult(
            slug=None,
            project_path=project_path,
            mutated=False,
            reason=reason,
        )
    return ActiveRunnerMutationResult(
        slug=reconciliation.cleared_slugs[0],
        project_path=project_path,
        mutated=True,
        reason=ACTIVE_RUNNER_CLEARED_REASON,
    )


async def notify_runner_of_gate_approval(cwd: str, slug: str, *, acting_session_id: str | None) -> bool:
    """Continue workflow after an accepted human approval fact commits.

    Emits the existing workflow update so the lifecycle router re-evaluates the
    todo, then notifies a distinct parked claimant when one remains live. Missing,
    closed, or concurrently disappearing claimants are best-effort outcomes.
    """
    project_path = resolve_project_root(cwd)
    todos_db = await get_workflow_store(project_path)
    await emit_todo_updated(slug=slug, project_root=str(project_path), source=_GATE_APPROVAL_EVENT_SOURCE)
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    active_runner = state.get("active_runner")
    if not isinstance(active_runner, str) or not active_runner or active_runner == acting_session_id:
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
