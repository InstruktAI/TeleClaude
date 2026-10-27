"""Operator/manual lifecycle-start lane.

In-process adoption, operator-START dispatch, the one-session-one-slug guard, and
claim reflection (working_slug backfill, title repair, and born-driver role
conferral). Extracted from ``lifecycle_runner`` so that module stays focused on
autonomous dispatch. Depends one-way on ``lifecycle_runner``'s spawn/claim
helpers; ``lifecycle_runner`` never imports this module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import DriverLaunchClass
from teleclaude.core.db import Db, get_db
from teleclaude.core.models import Session
from teleclaude.core.next_machine.git_ops import get_ref_commit
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lanes import PREPARE_AUTHOR_ROLES, WORK_LANE_ROLES
from teleclaude.core.next_machine.lifecycle import pending_approval_gate
from teleclaude.core.next_machine.lifecycle_runner import (
    SessionRunner,
    approval_from_state,
    artifact_digest_from_state,
    command_for_lane,
    default_session_runner,
    dispatch_lifecycle_session,
    load_runner_todos,
    make_intent,
    plan_review_current_from_state,
    recheck_slug_holder,
    resolve_kinded_dispatch,
    role_for_lane,
    set_active_runner,
)
from teleclaude.core.next_machine.runner_types import (
    DispatchIntent,
    DispatchOrigin,
    ManualLifecycleSessionResult,
    ManualLifecycleStatus,
    RunnerLane,
    RunnerSkipReason,
    RunnerTodo,
)
from teleclaude.core.next_machine.runtime.sessions import (
    PREPARE_LIFECYCLE_COMMANDS,
    find_live_commit_reviewer_for_initiator,
    find_live_commit_reviewer_for_terminal_human,
    find_live_reviewer_for_slug,
    resolve_slug_holders,
)
from teleclaude.core.next_machine.session_hold import reconcile_driver_ownership_for_session
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.session_title import compose_command_session_title
from teleclaude.core.todos_db._exceptions import (
    ClaimConflict,
    DriverStartBusy,
    LaneCrossingRefused,
    ReviewerConflict,
    ReviewerIdentityUnresolved,
)
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import Event, PrepareClaimDetail, TodoEventKind, TodoState

logger = get_logger(__name__)

_MAIN_REF = "main"
_ERR_CLAIM_BOUNDARY_UNRESOLVED = (
    "cannot record the prepare claim on {slug}: {ref} does not resolve, so the claim period has no boundary"
)

__all__ = [
    "DriverStartGuardResult",
    "adopt_headless_session",
    "adopt_manual_lifecycle_session",
    "driver_start_section",
    "guard_driver_start",
    "manual_start_lifecycle_session",
    "recheck_slug_holder",
    "resolve_manual_dispatch_intent",
    "work_feedback_for_manual_skip",
]


_SECTIONED_LANES = frozenset({RunnerLane.PREPARE, RunnerLane.WORK})
_LANE_ROLES: dict[RunnerLane, frozenset[str]] = {
    RunnerLane.PREPARE: PREPARE_AUTHOR_ROLES,
    RunnerLane.WORK: WORK_LANE_ROLES,
}
_SANCTIONED_PATH_FROM_PREPARE = (
    "complete the prepare lifecycle, whose terminal releases the claim; "
    "the lifecycle runner then dispatches a fresh work orchestrator"
)
_SANCTIONED_PATH_FROM_WORK = (
    "return the todo through `telec todo stamp {slug} --kickback --reason <why>`; "
    "the lifecycle runner then dispatches a fresh prepare orchestrator"
)
_SANCTIONED_PATH_BY_HELD_LANE: dict[RunnerLane, str] = {
    RunnerLane.PREPARE: _SANCTIONED_PATH_FROM_PREPARE,
    RunnerLane.WORK: _SANCTIONED_PATH_FROM_WORK,
}
_MANUAL_SKIP_FEEDBACK: dict[RunnerSkipReason, str] = {
    RunnerSkipReason.APPROVAL_PENDING: "This todo is waiting for approval; complete its approval step before starting work.",
    RunnerSkipReason.AT_CAPACITY: "All lifecycle driver slots are in use; try again when one becomes available.",
    RunnerSkipReason.DELIVERED: "This todo is already delivered and cannot be started again.",
    RunnerSkipReason.DEPENDENCY_BLOCKED: "This todo is blocked by dependencies; complete them before starting it.",
    RunnerSkipReason.FINALIZE_READY: "This todo is ready to finalize; finish its delivery before starting more work.",
    RunnerSkipReason.HELD: "This todo is on hold; release the hold before starting work.",
    RunnerSkipReason.ICEBOX: "This todo is in the icebox; unfreeze it before starting work.",
    RunnerSkipReason.POLICY_DISABLED: "The requested lifecycle lane is disabled for this todo.",
    RunnerSkipReason.REMOVED: "This todo is removed; reactivate it before starting work.",
    RunnerSkipReason.SCHEDULE_BLOCKED: "This todo is not scheduled to run yet; try again when its schedule allows.",
    RunnerSkipReason.TASK_AUTHORIZATION_MISSING: "This task is not authorized to run; approve its task plan first.",
}
_CONFLICTING_SESSION_BINDING_FEEDBACK = (
    "This session already owns another todo; finish or release that lifecycle claim before starting this one."
)


def work_feedback_for_manual_skip(reason: RunnerSkipReason | str | None) -> str | None:
    """Publish feedback only for deliberate manual-start work refusals."""
    if isinstance(reason, RunnerSkipReason):
        return _MANUAL_SKIP_FEEDBACK.get(reason)
    return None


_START_REFUSED_BUSY_EVENT = "driver start refused while another start is in progress"
_STARTS_IN_FLIGHT: dict[tuple[Path, str], str] = {}


@asynccontextmanager
async def driver_start_section(
    project_path: str | Path,
    slug: str,
    *,
    starting_session_id: str,
) -> AsyncIterator[None]:
    """Hold the one-start-at-a-time section for a todo while a start creates or claims its orchestrator.

    Keyed by the canonical project root and slug, whatever lane is asked for: the
    holder check admits one driver per todo. Entering never waits. A free key records
    ``starting_session_id`` and enters; a key held by another start raises
    :class:`DriverStartBusy` naming the session that start is creating or claiming.
    Leaving drops the record on success and on exception, so a failed start leaves
    nothing behind. The record lives in this process only; the registry check-and-set
    has no await in it, so on the daemon's event loop it is atomic. The caller
    re-checks the slug's holder inside the section and creates or claims before leaving.
    """
    key = (resolve_project_root(project_path), slug)
    in_flight = _STARTS_IN_FLIGHT.get(key)
    if in_flight is not None:
        busy = DriverStartBusy(slug=slug, in_flight=in_flight)
        logger.warning(
            _START_REFUSED_BUSY_EVENT,
            project=str(key[0]),
            slug=slug,
            in_flight=in_flight,
            starting_session_id=starting_session_id,
        )
        raise busy
    _STARTS_IN_FLIGHT[key] = starting_session_id
    try:
        yield
    finally:
        del _STARTS_IN_FLIGHT[key]


@dataclass(frozen=True)
class DriverStartGuardResult:
    """Authoritative driver-start facts needed by API-stage observation."""

    held_without_driver: bool = False


async def _reflect_claim_on_caller_session(
    runtime_db: Db,
    session: Session,
    slug: str,
    lane: RunnerLane,
) -> None:
    """Reflect an inline lifecycle claim onto the caller's session row.

    A lifecycle state-machine claim/adoption that binds ``slug`` to this session
    backfills the session's ``working_slug`` (so the session is the slug's
    authoritative owner for dedup and the mutation gate), repairs its title to
    the lane's role and slug (so the adoption is visible in the Sessions view),
    and confers the lane's born-driver ``role`` (via
    :func:`role_for_lane`) so the session reaches exact parity with a
    directly-started driver of the same lane instead of falling through the
    a role-less session.

    This fires both for a session that holds no claim yet (empty
    ``working_slug``) and for a session already bound to this same ``slug``
    in this same lane — calling the lifecycle machine adopts the role that
    comes with it. A session that holds the slug in the other SDLC lane never
    reaches this point (see :func:`_refuse_lane_crossing`). Claim ownership
    (checked by the caller before this runs) is the only gate; there is no
    additional role precondition. Each field is written only when it differs
    from the claimed lane's value, so the writes are idempotent — a session
    already at the lane's identity is left alone. A pre-existing *different*
    ``working_slug`` is a conflict refused by the caller before adoption, never
    silently overwritten here.
    """
    if session.working_slug and session.working_slug != slug:
        return
    command, _ = command_for_lane(lane)
    role = role_for_lane(lane, Path(session.project_path) if session.project_path else Path.cwd())
    desired_title = compose_command_session_title(command, slug, role=role)
    updates: dict[str, str] = {}
    if session.working_slug != slug:
        updates["working_slug"] = slug
    if session.title != desired_title:
        updates["title"] = desired_title
    if session.role != role:
        updates["role"] = role
    if updates:
        await runtime_db.update_session(session.session_id, **updates)


async def adopt_headless_session(
    *,
    runtime_db: Db,
    todos_db: WorkflowStore,
    slug: str,
    session_id: str,
    lane: RunnerLane = RunnerLane.WORK,
) -> bool:
    """Adopt a running headless session as a todo's manually-started driver.

    A headless session carries no lifecycle ownership while it runs. Adoption
    links it by writing `active_runner` paired with ``manually_started=True`` so
    the driver is tracked and excluded from the cap.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    await set_active_runner(todos_db, slug, session_id, lane=lane, manually_started=True, release_hold=True)
    session = await runtime_db.get_session(session_id)
    if session is not None and is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        reconciliation = await reconcile_driver_ownership_for_session(todos_db, session_id)
        logger.info(
            "terminal adopted lifecycle driver reconciled",
            session_id=session_id,
            cleared_slugs=",".join(reconciliation.cleared_slugs),
        )
    return True


async def _target_for_manual_start(
    todos_db: WorkflowStore,
    runtime_db: Db,
    slug: str,
    lane: RunnerLane,
    project_path: str | Path,
    *,
    check_dependencies: bool = True,
    caller_session_id: str | None = None,
) -> tuple[RunnerTodo | None, RunnerSkipReason | None, str | None]:
    todos, _ = await load_runner_todos(todos_db, runtime_db)
    todo = todos.get(slug)
    if todo is None:
        return None, RunnerSkipReason.MISSING_STATE, None
    if todo.status == "removed":
        return todo, RunnerSkipReason.REMOVED, None
    if todo.status == "delivered":
        return todo, RunnerSkipReason.DELIVERED, None
    if todo.status == "icebox":
        return todo, RunnerSkipReason.ICEBOX, None
    # Registry-authoritative dedup over the shared two-signal holder resolution.
    # A live orchestrator bound to the slug blocks a second manual start, but the
    # caller's own session is exempt so an orchestrator adopting/continuing its
    # own slug is not self-blocked. The active_runner check is caller-independent
    # so a live task runner refuses a duplicate even for the dispatching caller.
    holders = await resolve_slug_holders(runtime_db, project_path, slug, todo.active_runner)
    if holders.orchestrator_owner is not None and holders.orchestrator_owner != caller_session_id:
        return todo, RunnerSkipReason.ALREADY_DRIVEN, holders.orchestrator_owner
    if holders.live_runner is not None:
        return todo, RunnerSkipReason.ALREADY_DRIVEN, holders.live_runner
    if not check_dependencies:
        return todo, None, None
    if lane is RunnerLane.WORK:
        delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)
        unmet = [dep for dep in todo.after if dep not in delivered_slugs]
        if unmet:
            return todo, RunnerSkipReason.DEPENDENCY_BLOCKED, None
    if lane is RunnerLane.PREPARE:
        prepared_slugs = await effective_prepared_slugs_for_dependencies(todos_db)
        unmet = [dep for dep in todo.after if dep not in prepared_slugs]
        if unmet:
            return todo, RunnerSkipReason.DEPENDENCY_BLOCKED, None
    return todo, None, None


async def _guard_reviewer_start(
    project_path: str | Path,
    slug: str | None,
    *,
    command: str | None,
    caller_session_id: str | None,
    caller_human_email: str | None,
    thinking_mode: str,
    db: Db | None,
) -> None:
    """Refuse a reviewer create-door start that would duplicate a live reviewer.

    Dispatches on the two subject-identity forms named in
    ``@input#r1`` (fix-commit-review-reuse-is-prose-only-nothin): a slug-bound
    reviewer (``sdlc/review-build``, ``sdlc/review-plan``,
    ``sdlc/review-architecture``) is keyed by exact ``(project, slug, command)``;
    commit review (``sdlc/review-commits``, no todo slug) is keyed by
    ``(project, driver, command, thinking mode)`` — mode is part of that
    subject because doc-hygiene and code review use different thinking modes,
    and a mode-blind subject refuses the cheap lane as a duplicate of the
    expensive one. The driver is the caller's session when it has one, even if
    it also carries a human, and otherwise the caller's authenticated human
    (``caller_human_email``). Silent no-op only when the command cannot be
    resolved — a slugless subject whose caller has neither driver form is
    refused rather than silently admitted, since such a launch can never be
    found as a prior holder (see :class:`ReviewerIdentityUnresolved`).

    """
    if command is None:
        return
    runtime_db = db or await get_db()
    command_value = command
    if slug:
        # /review-plan and /review-architecture run at repo root
        # (subdir=None); every other slug-bound reviewer runs in the slug
        # worktree, the lookup's default scope.
        subdir_override = "" if command_value in PREPARE_LIFECYCLE_COMMANDS else None
        holder = await find_live_reviewer_for_slug(
            runtime_db, project_path, slug, command_value, subdir_override=subdir_override
        )
        subject = f"/{command_value} {slug}"
    else:
        subject = f"/{command_value} at {thinking_mode} for this project and driver"
        if caller_session_id:
            holder = await find_live_commit_reviewer_for_initiator(
                runtime_db, project_path, caller_session_id, command_value, thinking_mode
            )
        elif caller_human_email:
            holder = await find_live_commit_reviewer_for_terminal_human(
                runtime_db, project_path, caller_human_email, command_value, thinking_mode
            )
        else:
            raise ReviewerIdentityUnresolved(subject=subject)
    if holder is None:
        return
    raise ReviewerConflict(subject=subject, holder=holder, reuse_command=f"telec sessions send {holder}")


async def guard_driver_start(
    project_path: str | Path,
    slug: str | None,
    *,
    launch_class: DriverLaunchClass,
    caller_session_id: str | None,
    caller_human_email: str | None,
    command: str | None = None,
    thinking_mode: str,
    db: Db | None = None,
) -> DriverStartGuardResult:
    """Refuse a create-door driver start that would duplicate a live driver.

    A create door always writes a new session row, so the self-caller exemption
    that is correct for in-place adoption (the op door) is wrong here. The guard
    keys on the requested launch class and routes each to the matching signal of
    ADR-0052's two-signal model via the one shared :func:`_target_for_manual_start`
    check:

    - ``WORKER_CHILD`` → return without checking. An orchestrator and the
      producing workers it spawns (builder, fixer, finalizer, intaker, planner,
      drift analyzer) legitimately share ``working_slug``; deduping them would
      false-refuse the orchestrator-spawns-its-worker pattern.
    - ``ORCHESTRATOR`` → run the dedup with ``caller_session_id=None`` so the
      registry self-caller exemption is disabled; any live holder (registry owner
      or live ``active_runner``) refuses, INCLUDING the caller itself — a second
      orchestrator row for a driven slug is never legitimate.
    - ``TASK_LANE`` → run the dedup with the real ``caller_session_id`` so a
      dispatching orchestrator self-exempts on the registry path, while the
      caller-independent ``active_runner`` check refuses a duplicate task runner.
    - ``REVIEWER`` → refuse against a live reviewer already open for the same
      review subject (see :func:`_guard_reviewer_start`), reached even when
      ``slug`` is ``None`` — commit review carries no todo slug at all.

    Raises :class:`ClaimConflict` (carrying the holder) when a live driver already
    holds the slug, :class:`ReviewerConflict` when a live reviewer already holds
    the review subject, or :class:`ReviewerIdentityUnresolved` when a slugless
    reviewer subject has neither a caller session nor a caller human to key dedup
    on (``caller_human_email`` is the terminal driver form, used only when
    ``caller_session_id`` is unset); returns silently
    when the start is allowed (no live holder, or a producing worker child-spawn),
    returning the authoritative held-without-driver fact for stage evidence.
    """
    if launch_class is DriverLaunchClass.REVIEWER:
        await _guard_reviewer_start(
            project_path,
            slug,
            command=command,
            caller_session_id=caller_session_id,
            caller_human_email=caller_human_email,
            thinking_mode=thinking_mode,
            db=db,
        )
        return DriverStartGuardResult()
    if launch_class is DriverLaunchClass.WORKER_CHILD:
        return DriverStartGuardResult()
    if not slug:
        return DriverStartGuardResult()
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_workflow_store(project_root)
    effective_caller = None if launch_class is DriverLaunchClass.ORCHESTRATOR else caller_session_id
    todo, reason, holder = await _target_for_manual_start(
        todos_db,
        runtime_db,
        slug,
        RunnerLane.PREPARE,
        project_root,
        check_dependencies=False,
        caller_session_id=effective_caller,
    )
    if reason is RunnerSkipReason.ALREADY_DRIVEN:
        raise ClaimConflict(slug=slug, holder=holder)
    return DriverStartGuardResult(held_without_driver=bool(todo and todo.hold and holder is None))


async def manual_start_lifecycle_session(
    project_path: str | Path,
    slug: str,
    *,
    lane: RunnerLane,
    db: Db | None = None,
    client_factory: Callable[[], SessionRunner] = default_session_runner,
) -> ManualLifecycleSessionResult:
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_workflow_store(project_root)
    _todo, reason, owner_session_id = await _target_for_manual_start(todos_db, runtime_db, slug, lane, project_root)
    if reason is not None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.ALREADY_DRIVEN
            if reason is RunnerSkipReason.ALREADY_DRIVEN
            else ManualLifecycleStatus.SKIPPED,
            session_id=owner_session_id if reason is RunnerSkipReason.ALREADY_DRIVEN else None,
            reason=reason,
        )

    client = client_factory()
    await client.connect()
    try:
        session_id = await dispatch_lifecycle_session(
            client=client,
            runtime_db=runtime_db,
            todos_db=todos_db,
            project_path=str(project_root),
            intent=make_intent(slug, lane),
            origin=DispatchOrigin.MANUAL,
        )
    except ClaimConflict as conflict:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.ALREADY_DRIVEN,
            session_id=conflict.holder,
            reason=RunnerSkipReason.ALREADY_DRIVEN,
        )
    finally:
        await client.close()

    return ManualLifecycleSessionResult(
        slug=slug,
        lane=lane,
        status=ManualLifecycleStatus.DISPATCHED,
        session_id=session_id,
    )


def _lane_of_role(role: str | None) -> RunnerLane | None:
    """Return the SDLC lane a session role belongs to, or ``None`` when no lane owns it."""
    for lane, roles in _LANE_ROLES.items():
        if role in roles:
            return lane
    return None


async def _refuse_lane_crossing(
    runtime_db: Db,
    todo: RunnerTodo | None,
    slug: str,
    caller_session_id: str,
    requested_lane: RunnerLane,
) -> None:
    """Refuse a caller that holds ``slug`` in the other SDLC lane, before any claim write.

    The caller holds the slug when it is the todo's ``active_runner`` or its session
    row is bound to the slug. Its lane is read from its ``role``; a role no lane owns
    (reviewers, drift analyzers, standing roles, unbound sessions) is never refused.
    The refusal names how the todo changes hands through the lifecycle runner instead.
    """
    session = await runtime_db.get_session(caller_session_id)
    holds_slug = (todo is not None and todo.active_runner == caller_session_id) or (
        session is not None and session.working_slug == slug
    )
    held_lane = _lane_of_role(session.role if session is not None else None)
    if not holds_slug or held_lane is None or held_lane is requested_lane or requested_lane not in _LANE_ROLES:
        return
    raise LaneCrossingRefused(
        slug=slug,
        held_lane=held_lane.value,
        requested_lane=requested_lane.value,
        sanctioned_path=_SANCTIONED_PATH_BY_HELD_LANE[held_lane].format(slug=slug),
    )


async def _record_prepare_claim(
    todos_db: WorkflowStore,
    slug: str,
    caller_session_id: str,
    project_root: Path,
    *,
    continuing_claim_is_recorded: bool,
) -> None:
    """Append the claim-entry event that bounds the caller's prepare claim period.

    The event carries main's HEAD at entry: commits after it are the claim
    period's, whatever second git stamped them in. A claim's start is the first
    prepare call that confirms it. With
    ``continuing_claim_is_recorded`` the call continues a live claim and records
    nothing when the todo's latest claim-entry event already names the caller;
    otherwise the call begins a new claim and always records. A claim whose
    boundary cannot be resolved is refused rather than recorded unbounded.
    """
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return
    writer = StateWriter(raw_state)
    latest_claimant = next(
        (event.actor for event in reversed(writer.state.events) if event.kind == TodoEventKind.PREPARE_CLAIM), None
    )
    if continuing_claim_is_recorded and latest_claimant == caller_session_id:
        return
    main_head = get_ref_commit(str(project_root), _MAIN_REF)
    if not main_head:
        raise RuntimeError(_ERR_CLAIM_BOUNDARY_UNRESOLVED.format(slug=slug, ref=_MAIN_REF))
    details: dict[str, StateValue] = {PrepareClaimDetail.MAIN_HEAD: main_head}
    writer.state.events.append(
        Event(
            at=datetime.now(UTC).isoformat(),
            actor=caller_session_id,
            kind=TodoEventKind.PREPARE_CLAIM,
            details=details,
        )
    )
    await writer.commit(todos_db, slug)


async def _claim_for_caller(
    runtime_db: Db,
    todos_db: WorkflowStore,
    slug: str,
    session: Session,
    lane: RunnerLane,
) -> bool:
    """Make ``session`` the slug's orchestrator: write ``active_runner``, then reflect the claim onto its row.

    Returns ``False`` when the slug has no workflow state to claim.
    """
    adopted = await adopt_headless_session(
        runtime_db=runtime_db,
        todos_db=todos_db,
        slug=slug,
        session_id=session.session_id,
        lane=lane,
    )
    if adopted:
        await _reflect_claim_on_caller_session(runtime_db, session, slug, lane)
    return adopted


async def adopt_manual_lifecycle_session(
    project_path: str | Path,
    slug: str,
    caller_session_id: str,
    *,
    db: Db | None = None,
    requested_lane: RunnerLane | None = None,
) -> ManualLifecycleSessionResult:
    """Claim an unclaimed slug in-process for a by-hand operator invocation.

    A manual invocation on an unclaimed todo (no live holder; earlier branches
    return ``ALREADY_DRIVEN`` when a different live session holds it) claims the
    slug in-process for the calling session — ``active_runner = caller``,
    ``manually_started = True`` — and clears any stored hold as part of that
    successful manual start. The only binding requirement is a live caller
    session: a session id with no registry row returns ``NOT_BOUND``. The
    operation bridge then runs the state machine in the calling session; no
    separate orchestrator is dispatched.

    ``requested_lane`` is the caller's actually-invoked lane (``telec todo
    prepare`` passes PREPARE, ``telec todo work`` passes WORK). It overrides the
    ``lifecycle_phase``-based heuristic below for non-task todos when supplied.
    The heuristic alone is ambiguous exactly at ``lifecycle_phase == PREPARED``:
    that value means both "prepare just finished, entering work" and "a
    work-entry drift bounce fired before the prepared → build_started
    transition, entering prepare" — two opposite intents at the same phase
    value. A caller that knows which command it invoked removes the ambiguity;
    a caller that does not (existing test call sites, headless adoption)
    falls back to the heuristic unchanged.

    A prepare or work adoption makes the caller the slug's orchestrator without a new
    session row, so it takes the todo's driver-start section (:func:`driver_start_section`)
    around a slug-scoped holder re-check and the ownership writes: a holder that appeared
    since the guard returns ``ALREADY_DRIVEN`` naming it, and a start already in progress
    raises :class:`DriverStartBusy`. Task lanes take no section.

    Raises :class:`LaneCrossingRefused` before any claim write or role reflection
    when the caller holds ``slug`` in the other SDLC lane.
    """
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_workflow_store(project_root)
    todo, reason, owner_session_id = await _target_for_manual_start(
        todos_db,
        runtime_db,
        slug,
        RunnerLane.PREPARE,
        project_root,
        check_dependencies=False,
        caller_session_id=caller_session_id,
    )
    lane = RunnerLane.PREPARE
    task_skip_reason: RunnerSkipReason | None = None
    if todo is not None:
        if todo.kind == KIND_TASK:
            lane, task_skip_reason = _manual_task_lane(todo)
        elif requested_lane is not None:
            lane = requested_lane
        elif todo.lifecycle_phase == LifecyclePhase.PREPARED.value:
            lane = RunnerLane.WORK
    await _refuse_lane_crossing(runtime_db, todo, slug, caller_session_id, lane)
    if todo is not None and todo.active_runner == caller_session_id:
        await set_active_runner(todos_db, slug, caller_session_id, lane=lane, manually_started=True, release_hold=False)
        active_session = await runtime_db.get_session(caller_session_id)
        if active_session is not None:
            await _reflect_claim_on_caller_session(runtime_db, active_session, slug, lane)
        if lane is RunnerLane.PREPARE:
            await _record_prepare_claim(
                todos_db, slug, caller_session_id, project_root, continuing_claim_is_recorded=True
            )
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.ALREADY_ACTIVE,
            session_id=caller_session_id,
        )
    if reason is RunnerSkipReason.ALREADY_DRIVEN:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.ALREADY_DRIVEN,
            session_id=owner_session_id,
            reason=reason,
            work_feedback=work_feedback_for_manual_skip(reason),
        )
    if reason is not None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=reason,
            work_feedback=work_feedback_for_manual_skip(reason),
        )
    if task_skip_reason is not None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=task_skip_reason,
            work_feedback=work_feedback_for_manual_skip(task_skip_reason),
        )

    session = await runtime_db.get_session(caller_session_id)
    if session is None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.NOT_BOUND,
            reason="caller-session-missing",
        )
    # One session, one slug: a caller already bound to a different slug cannot
    # upgrade into this one — a conflicting session binding, refused (not a
    # second slot). A matching binding falls through and re-confirms the claim.
    if session.working_slug and session.working_slug != slug:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=f"conflicting session binding: caller owns working_slug={session.working_slug}",
            work_feedback=_CONFLICTING_SESSION_BINDING_FEEDBACK,
        )
    if lane in _SECTIONED_LANES:
        async with driver_start_section(project_root, slug, starting_session_id=caller_session_id):
            holder = await recheck_slug_holder(
                runtime_db, todos_db, project_root, slug, exempt_session_id=caller_session_id
            )
            if holder is not None:
                return ManualLifecycleSessionResult(
                    slug=slug,
                    lane=lane,
                    status=ManualLifecycleStatus.ALREADY_DRIVEN,
                    session_id=holder,
                    reason=RunnerSkipReason.ALREADY_DRIVEN,
                    work_feedback=work_feedback_for_manual_skip(RunnerSkipReason.ALREADY_DRIVEN),
                )
            adopted = await _claim_for_caller(runtime_db, todos_db, slug, session, lane)
    else:
        adopted = await _claim_for_caller(runtime_db, todos_db, slug, session, lane)
    if not adopted:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=RunnerSkipReason.MISSING_STATE,
        )
    if lane is RunnerLane.PREPARE:
        await _record_prepare_claim(todos_db, slug, caller_session_id, project_root, continuing_claim_is_recorded=False)
    return ManualLifecycleSessionResult(
        slug=slug,
        lane=lane,
        status=ManualLifecycleStatus.ADOPTED,
        session_id=caller_session_id,
    )


async def resolve_manual_dispatch_intent(
    todos_db: WorkflowStore,
    slug: str,
    *,
    requested_lane: RunnerLane | None = None,
) -> tuple[DispatchIntent | None, RunnerSkipReason | None]:
    """Resolve the natural lifecycle lane for an operator-started todo.

    An explicit ``requested_lane`` of PREPARE re-opens the prepare lane for a todo
    whose natural lane has advanced to WORK (the drift re-preparation route). The
    flip is asymmetric: it fires only on an already-resolved WORK lane, so a
    naturally-PREPARE draft is unaffected.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return None, RunnerSkipReason.MISSING_STATE
    raw_kind = state.get("kind")
    kind_value = raw_kind if isinstance(raw_kind, str) else None
    try:
        kind = canonical_kind(kind_value)
    except ValueError:
        return None, RunnerSkipReason.INVALID_KIND

    deps = await todos_db.load_deps()
    raw_phase = state.get("lifecycle_phase")
    lifecycle_phase = raw_phase if isinstance(raw_phase, str) else None
    task_approval = approval_from_state(state, "task_approved")
    todo = RunnerTodo(
        slug=slug,
        status="active",
        kind=kind,
        lifecycle_phase=lifecycle_phase,
        human_approval_pending=pending_approval_gate(TodoState.model_validate(state)) is not None,
        hold=state.get("hold") is True,
        active_runner=None,
        after=tuple(deps.get(slug, [])),
        schedule=await todos_db.get_schedule(slug),
        task_plan_digest=artifact_digest_from_state(state, "task_plan"),
        task_approved=task_approval[0],
        task_approved_digest=task_approval[1],
        plan_review_current=plan_review_current_from_state(state),
    )
    prepared_slugs = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)
    lane, skip_reason = resolve_kinded_dispatch(
        todo,
        kind,
        prepared_slugs=prepared_slugs,
        delivered_slugs=delivered_slugs,
        autostart={
            KIND_FEATURE: True,
            KIND_CHANGE: True,
            KIND_BUG: True,
            KIND_TASK: True,
        },
    )
    if lane is None:
        return None, skip_reason or RunnerSkipReason.INVALID_KIND
    if requested_lane is RunnerLane.PREPARE and lane is RunnerLane.WORK:
        lane = RunnerLane.PREPARE
    return make_intent(slug, lane), None


def _manual_task_lane(todo: RunnerTodo) -> tuple[RunnerLane, RunnerSkipReason | None]:
    if not todo.task_plan_digest:
        return RunnerLane.TASK_PREPARE, None
    if not todo.task_approved or todo.task_approved_digest != todo.task_plan_digest:
        return RunnerLane.TASK_PREPARE, RunnerSkipReason.TASK_AUTHORIZATION_MISSING
    return RunnerLane.TASK_RUN, None
