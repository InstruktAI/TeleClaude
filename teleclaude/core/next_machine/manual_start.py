"""Operator/manual lifecycle-start lane.

In-process adoption, operator-START dispatch, the one-session-one-slug guard, and
claim reflection (working_slug backfill, title repair, and born-driver role
conferral). Extracted from ``lifecycle_runner`` so that module stays focused on
autonomous dispatch. Depends one-way on ``lifecycle_runner``'s spawn/claim
helpers; ``lifecycle_runner`` never imports this module.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from teleclaude.constants import DriverLaunchClass
from teleclaude.core.db import Db, get_db
from teleclaude.core.models import Session
from teleclaude.core.next_machine.dispatch_claims import acquire_dispatch_claim, release_dispatch_claim
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lifecycle_runner import (
    SessionRunner,
    approval_from_state,
    artifact_digest_from_state,
    command_for_lane,
    default_session_runner,
    dispatch_lifecycle_session,
    load_runner_todos,
    make_intent,
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
from teleclaude.core.next_machine.runtime.sessions import resolve_slug_holders
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.core.todos_db._exceptions import ClaimConflict
from teleclaude.project_root import resolve_project_root
from teleclaude.types.lifecycle import LifecyclePhase

__all__ = [
    "adopt_headless_session",
    "adopt_manual_lifecycle_session",
    "guard_driver_start",
    "manual_start_lifecycle_session",
    "resolve_manual_dispatch_intent",
]


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
    the lane's command shape (so the adoption is visible in the Sessions view),
    and confers the lane's born-driver ``system_role`` and ``job`` (via
    :func:`role_for_lane`) so the session reaches exact parity with a
    directly-started driver of the same lane instead of falling through the
    caller-verification ``working_slug`` ⇒ worker fallback.

    This fires both for a session that holds no claim yet (empty
    ``working_slug``) and for a session already bound to this same ``slug``
    under a different lane — calling either lifecycle machine implicitly
    adopts the role that comes with it, for whichever lane the caller already
    legitimately claims. Claim ownership (checked by the caller before this
    runs) is the only gate; there is no additional role precondition. Each
    field is written only when it differs from the claimed lane's value, so
    the writes are idempotent — a session already at the lane's identity is
    left alone. A pre-existing *different* ``working_slug`` is a conflict
    refused by the caller before adoption, never silently overwritten here.
    """
    if session.working_slug and session.working_slug != slug:
        return
    command, _, _ = command_for_lane(lane)
    desired_title = f"{command} {slug}"
    system_role, job = role_for_lane(lane)
    updates: dict[str, str] = {}
    if session.working_slug != slug:
        updates["working_slug"] = slug
    if session.title != desired_title:
        updates["title"] = desired_title
    if session.system_role != system_role:
        updates["system_role"] = system_role
    if session.job != job.value:
        updates["job"] = job.value
    if updates:
        await runtime_db.update_session(session.session_id, **updates)


async def adopt_headless_session(
    *,
    todos_db: TodosDb,
    slug: str,
    session_id: str,
    lane: RunnerLane = RunnerLane.WORK,
) -> bool:
    """Adopt a running headless session as a todo's manually-started driver.

    A headless session carries no claim while it runs — the runner never
    auto-claims a session it did not spawn. Adoption is the explicit manual act
    that links it: it acquires the same `(slug, lane)` dispatch claim the spawn
    primitive uses, then writes `active_runner` paired with
    ``manually_started=True`` so the driver is tracked and excluded from the cap.

    Returns ``True`` on success, ``False`` when the claim is already held (an
    in-flight dispatch already owns this slug/lane) or no state exists for the
    slug.
    """
    owner = f"headless-adoption:{slug}"
    acquired = await acquire_dispatch_claim(todos_db, slug=slug, lane=lane.value, owner=owner)
    if not acquired:
        return False
    state = await todos_db.read_state(slug)
    if state is None:
        await release_dispatch_claim(todos_db, slug=slug, lane=lane.value, owner=owner)
        return False
    await set_active_runner(todos_db, slug, session_id, lane=lane, manually_started=True)
    return True


async def _target_for_manual_start(
    todos_db: TodosDb,
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


async def guard_driver_start(
    project_path: str | Path,
    slug: str,
    *,
    launch_class: DriverLaunchClass,
    caller_session_id: str | None,
    db: Db | None = None,
) -> None:
    """Refuse a create-door driver start that would duplicate a live driver.

    A create door always writes a new session row, so the self-caller exemption
    that is correct for in-place adoption (the op door) is wrong here. The guard
    keys on the requested launch class and routes each to the matching signal of
    ADR-0052's two-signal model via the one shared :func:`_target_for_manual_start`
    check:

    - ``WORKER_CHILD`` → return without checking. An orchestrator and the workers
      it spawns legitimately share ``working_slug``; deduping them would
      false-refuse the orchestrator-spawns-its-worker pattern.
    - ``ORCHESTRATOR`` → run the dedup with ``caller_session_id=None`` so the
      registry self-caller exemption is disabled; any live holder (registry owner
      or live ``active_runner``) refuses, INCLUDING the caller itself — a second
      orchestrator row for a driven slug is never legitimate.
    - ``TASK_LANE`` → run the dedup with the real ``caller_session_id`` so a
      dispatching orchestrator self-exempts on the registry path, while the
      caller-independent ``active_runner`` check refuses a duplicate task runner.

    Raises :class:`ClaimConflict` (carrying the holder) when a live driver already
    holds the slug; returns silently when the start is allowed (no live holder, or
    a worker child-spawn).
    """
    if launch_class is DriverLaunchClass.WORKER_CHILD:
        return
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_todos_db(project_root)
    effective_caller = None if launch_class is DriverLaunchClass.ORCHESTRATOR else caller_session_id
    _todo, reason, holder = await _target_for_manual_start(
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
    todos_db = await get_todos_db(project_root)
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
            todos_db=todos_db,
            project_path=str(project_root),
            intent=make_intent(slug, lane),
            origin=DispatchOrigin.MANUAL,
        )
    finally:
        await client.close()

    if session_id is None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=RunnerSkipReason.CLAIMED,
        )
    return ManualLifecycleSessionResult(
        slug=slug,
        lane=lane,
        status=ManualLifecycleStatus.DISPATCHED,
        session_id=session_id,
    )


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
    """
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_todos_db(project_root)
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
    if todo is not None and todo.active_runner == caller_session_id:
        await set_active_runner(todos_db, slug, caller_session_id, lane=lane, manually_started=True)
        active_session = await runtime_db.get_session(caller_session_id)
        if active_session is not None:
            await _reflect_claim_on_caller_session(runtime_db, active_session, slug, lane)
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
        )
    if reason is not None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=reason,
        )
    if task_skip_reason is not None:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=task_skip_reason,
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
        )
    adopted = await adopt_headless_session(todos_db=todos_db, slug=slug, session_id=caller_session_id, lane=lane)
    if not adopted:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=RunnerSkipReason.CLAIMED,
        )
    await _reflect_claim_on_caller_session(runtime_db, session, slug, lane)
    return ManualLifecycleSessionResult(
        slug=slug,
        lane=lane,
        status=ManualLifecycleStatus.ADOPTED,
        session_id=caller_session_id,
    )


async def resolve_manual_dispatch_intent(
    todos_db: TodosDb,
    slug: str,
    *,
    requested_lane: RunnerLane | None = None,
) -> tuple[DispatchIntent | None, RunnerSkipReason | None]:
    """Resolve the natural lifecycle lane for an operator-started todo.

    An explicit ``requested_lane`` of PREPARE re-opens the prepare lane for a todo
    whose natural lane has advanced to WORK (the drift re-preparation route). The
    flip is asymmetric: it fires only on an already-resolved WORK lane, so a
    kind-less todo remains undispatched and a naturally-PREPARE draft is
    unaffected.
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
        hold=state.get("hold") is True,
        active_runner=None,
        after=tuple(deps.get(slug, [])),
        schedule=await todos_db.get_schedule(slug),
        task_plan_digest=artifact_digest_from_state(state, "task_plan"),
        task_approved=task_approval[0],
        task_approved_digest=task_approval[1],
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
