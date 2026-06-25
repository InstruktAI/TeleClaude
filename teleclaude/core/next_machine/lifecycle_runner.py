"""State-derived lifecycle runner dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol, Unpack

from instrukt_ai_logging import get_logger

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.cli.api_client import RunSessionArgs, TelecAPIClient
from teleclaude.config import WorkflowRunnerMode, config
from teleclaude.constants import DriverLaunchClass
from teleclaude.core.dates import task_schedule_due
from teleclaude.core.db import Db, get_db
from teleclaude.core.next_machine.dispatch_claims import (
    acquire_dispatch_claim,
    list_dispatch_claims,
    release_dispatch_claim,
)
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lifecycle import (
    coerce_lifecycle_phase,
    effective_hold,
    lifecycle_phase_index,
    pending_approval_gate,
)
from teleclaude.core.next_machine.runner_order import dependency_first_order
from teleclaude.core.next_machine.runner_types import (
    DispatchIntent,
    DispatchOrigin,
    ManualLifecycleSessionResult,
    ManualLifecycleStatus,
    RunnerDecision,
    RunnerLane,
    RunnerResult,
    RunnerSkipReason,
    RunnerTodo,
)
from teleclaude.core.next_machine.runtime.sessions import (
    is_live_session_id,
    live_orchestrator_owned_slugs,
    resolve_slug_holders,
)
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.task_wake import wake_due_recurring_tasks
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.core.todos_db._exceptions import ClaimConflict
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.project_root import resolve_state_root
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue

logger = get_logger(__name__)

_ADDITIONAL_CONTEXT = "human_in_loop: false\n"


# Steady-state terminal reasons carry the entire backlog and never change
# actionably; the runner log keeps their counts but omits the slug flood.
_TERMINAL_SKIP_REASONS: frozenset[RunnerSkipReason] = frozenset(
    {
        RunnerSkipReason.DELIVERED,
        RunnerSkipReason.REMOVED,
        RunnerSkipReason.ICEBOX,
    }
)


class SessionRunner(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO: ...


def default_session_runner() -> SessionRunner:
    return TelecAPIClient()


def _command_for_lane(lane: RunnerLane) -> tuple[str, str | None, str]:
    if lane is RunnerLane.ANALYZE:
        return "/analyze-todo-input", None, _ADDITIONAL_CONTEXT
    if lane is RunnerLane.TASK_PREPARE:
        return "/next-prepare-task", "med", _ADDITIONAL_CONTEXT
    if lane is RunnerLane.TASK_RUN:
        return "/next-run-task", "med", ""
    if lane is RunnerLane.WORK:
        return "/next-work", "med", ""
    return "/next-prepare", "slow", _ADDITIONAL_CONTEXT


def _intent(slug: str, lane: RunnerLane) -> DispatchIntent:
    command, thinking_mode, additional_context = _command_for_lane(lane)
    return DispatchIntent(
        slug=slug,
        lane=lane,
        command=command,
        thinking_mode=thinking_mode,
        additional_context=additional_context,
    )


def _autostart_enabled(kind: str, autostart: Mapping[str, bool]) -> bool:
    return bool(autostart.get(kind, False))


def _pending_approval_gate_for_runner(todo: RunnerTodo) -> bool:
    return (
        pending_approval_gate(
            {
                "kind": todo.kind,
                "lifecycle_phase": todo.lifecycle_phase,
            }
        )
        is not None
    )


def _resolve_kinded_dispatch(
    todo: RunnerTodo,
    kind: str,
    *,
    prepared_slugs: set[str],
    delivered_slugs: set[str],
    autostart: Mapping[str, bool],
    now: datetime | None = None,
) -> tuple[RunnerLane | None, RunnerSkipReason | None]:
    """Resolve the dispatch lane (or skip reason) for a kinded todo."""
    if kind == KIND_TASK:
        if not todo.task_plan_digest:
            return RunnerLane.TASK_PREPARE, None
        if not todo.task_approved or todo.task_approved_digest != todo.task_plan_digest:
            return None, RunnerSkipReason.TASK_AUTHORIZATION_MISSING
        if not task_schedule_due(todo.schedule, now=now):
            return None, RunnerSkipReason.SCHEDULE_BLOCKED
        unmet = [dep for dep in todo.after if dep not in delivered_slugs]
        if unmet:
            return None, RunnerSkipReason.DEPENDENCY_BLOCKED
        # Autonomous run honors autostart.task; the manual path passes an
        # all-True map so operator-initiated starts are unaffected. Prepare
        # stays ungated above, symmetric with the SDLC prepare branch.
        if not _autostart_enabled(KIND_TASK, autostart):
            return None, RunnerSkipReason.POLICY_DISABLED
        return RunnerLane.TASK_RUN, None
    if kind not in {KIND_FEATURE, KIND_CHANGE, KIND_BUG}:
        return None, RunnerSkipReason.INVALID_KIND
    phase = coerce_lifecycle_phase(todo.lifecycle_phase)
    if phase is None:
        return None, RunnerSkipReason.UNKNOWN_PHASE
    if phase == LifecyclePhase.FINALIZE_READY:
        return None, RunnerSkipReason.FINALIZE_READY
    if lifecycle_phase_index(phase) >= lifecycle_phase_index(LifecyclePhase.PREPARED):
        # Work lane — entering the execution runtime. Autostart gates this only.
        if not _autostart_enabled(kind, autostart):
            return None, RunnerSkipReason.POLICY_DISABLED
        unmet = [dep for dep in todo.after if dep not in delivered_slugs]
        lane = RunnerLane.WORK
    else:
        # Prepare lane — preparation always runs regardless of autostart; agents
        # park at the human approval gates (PRD) at the right moments anyway.
        unmet = [dep for dep in todo.after if dep not in prepared_slugs]
        lane = RunnerLane.PREPARE
    if unmet:
        return None, RunnerSkipReason.DEPENDENCY_BLOCKED
    return lane, None


def decide_dispatches(
    todos: Mapping[str, RunnerTodo],
    *,
    prepared_slugs: set[str],
    delivered_slugs: set[str],
    autostart: Mapping[str, bool],
    live_session_ids: set[str],
    orchestrator_owned_slugs: set[str] | None = None,
    claimed: set[tuple[str, RunnerLane]] | None = None,
    max_dispatch: int = 5,
    live_driver_count: int = 0,
    runner_mode: WorkflowRunnerMode = WorkflowRunnerMode.AUTOSTART,
    now: datetime | None = None,
) -> RunnerDecision:
    decision = RunnerDecision(evaluated=len(todos))
    # Manual mode is the operator's runaway brake: the runner performs no
    # autonomous dispatch on any lane. The manual-start path
    # (resolve_manual_dispatch_intent) never reaches here, so it stays ungated.
    if runner_mode is WorkflowRunnerMode.MANUAL:
        return decision
    active_claims = claimed or set()
    owned_slugs = orchestrator_owned_slugs or set()
    # Concurrency budget: how many more drivers may go live this pass. Each
    # dispatched intent consumes one slot on top of the already-live drivers.
    # Only non-manually_started drivers count: a human START or a headless
    # adoption is never charged against the auto-dispatch cap (the caller passes
    # the non-manual live count here).
    remaining_budget = max(0, max_dispatch - live_driver_count)

    def _at_capacity() -> bool:
        return remaining_budget - len(decision.intents) <= 0

    for slug in dependency_first_order(todos):
        todo = todos[slug]
        if todo.status == "removed":
            decision.skip(RunnerSkipReason.REMOVED, slug)
            continue
        if todo.status == "delivered":
            decision.skip(RunnerSkipReason.DELIVERED, slug)
            continue
        if todo.status == "icebox":
            decision.skip(RunnerSkipReason.ICEBOX, slug)
            continue
        # Approval-pending and held are independent skips with no precedence.
        if _pending_approval_gate_for_runner(todo):
            decision.skip(RunnerSkipReason.APPROVAL_PENDING, slug)
            continue
        try:
            held_kind = canonical_kind(todo.kind) if todo.kind is not None else None
        except ValueError:
            held_kind = todo.kind
        # Resolve autostart_active from the function's explicit inputs only — the
        # runner_mode and the autostart map it already receives — never global
        # config, so the decision stays pure over its parameters. (runner_mode is
        # AUTOSTART here: MANUAL returned early above.)
        autostart_active = held_kind == KIND_TASK or (
            runner_mode is WorkflowRunnerMode.AUTOSTART
            and held_kind is not None
            and held_kind in autostart
            and _autostart_enabled(held_kind, autostart)
        )
        if effective_hold(hold=todo.hold, lifecycle_phase=todo.lifecycle_phase, autostart_active=autostart_active):
            decision.skip(RunnerSkipReason.HELD, slug)
            continue
        # Orchestrator dedup is registry-authoritative: a live orchestrator bound
        # to the slug (registry working_slug) blocks a second one regardless of
        # how it was started. The active_runner branch remains the dedup signal
        # for non-orchestrator (task-lane) drivers, which carry no orchestrator
        # session_role in the registry.
        if slug in owned_slugs or (todo.active_runner and todo.active_runner in live_session_ids):
            decision.skip(RunnerSkipReason.ALREADY_DRIVEN, slug)
            continue
        if todo.kind is None:
            # Kind-discovery is preparation — it always runs (capped/deduped),
            # never gated by autostart, so kindless todos get classified and
            # prepared regardless of the work-lane autostart policy.
            lane = RunnerLane.ANALYZE
            if (slug, lane) in active_claims:
                decision.skip(RunnerSkipReason.CLAIMED, slug)
                continue
            if _at_capacity():
                decision.skip(RunnerSkipReason.AT_CAPACITY, slug)
                continue
            decision.intents.append(_intent(slug, lane))
            continue
        try:
            kind = canonical_kind(todo.kind)
        except ValueError:
            decision.skip(RunnerSkipReason.INVALID_KIND, slug)
            continue
        lane, skip_reason = _resolve_kinded_dispatch(
            todo,
            kind,
            prepared_slugs=prepared_slugs,
            delivered_slugs=delivered_slugs,
            autostart=autostart,
            now=now,
        )
        if lane is None:
            decision.skip(skip_reason or RunnerSkipReason.INVALID_KIND, slug)
            continue
        if (slug, lane) in active_claims:
            decision.skip(RunnerSkipReason.CLAIMED, slug)
            continue
        if _at_capacity():
            decision.skip(RunnerSkipReason.AT_CAPACITY, slug)
            continue
        decision.intents.append(_intent(slug, lane))
    return decision


async def _is_live_runner(db: Db, session_id: str | None) -> bool:
    return bool(session_id and await is_live_session_id(db, session_id))


async def _read_runner_todo(todos_db: TodosDb, row: TodoRow) -> RunnerTodo | None:
    if row["status"] in {"delivered", "removed"}:
        return RunnerTodo(
            slug=row["slug"],
            status=row["status"],
            kind=None,
            lifecycle_phase=None,
            hold=False,
            active_runner=None,
            after=(),
            schedule=row["schedule"],
        )
    state = await todos_db.read_state(row["slug"])
    if state is None:
        return None
    return _todo_from_state(row, state)


def _todo_from_state(row: TodoRow, state: Mapping[str, StateValue]) -> RunnerTodo:
    kind = state.get("kind")
    phase = state.get("lifecycle_phase")
    active_runner = state.get("active_runner")
    task_plan_digest = _artifact_digest_from_state(state, "task_plan")
    task_approval = _approval_from_state(state, "task_approved")
    return RunnerTodo(
        slug=row["slug"],
        status=row["status"],
        kind=kind if isinstance(kind, str) else None,
        lifecycle_phase=phase if isinstance(phase, str) else None,
        hold=state.get("hold") is True,
        active_runner=active_runner if isinstance(active_runner, str) and active_runner else None,
        manually_started=state.get("manually_started") is True,
        after=(),
        schedule=row["schedule"],
        task_plan_digest=task_plan_digest,
        task_approved=task_approval[0],
        task_approved_digest=task_approval[1],
    )


def _artifact_digest_from_state(state: Mapping[str, StateValue], artifact_key: str) -> str:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return ""
    artifact = artifacts.get(artifact_key)
    if not isinstance(artifact, Mapping):
        return ""
    digest = artifact.get("digest")
    return digest if isinstance(digest, str) else ""


def _approval_from_state(state: Mapping[str, StateValue], approval_key: str) -> tuple[bool, str]:
    approvals = state.get("approvals")
    if not isinstance(approvals, Mapping):
        return False, ""
    approval = approvals.get(approval_key)
    if not isinstance(approval, Mapping):
        return False, ""
    approved_digest = approval.get("approved_digest")
    return approval.get("approved") is True, approved_digest if isinstance(approved_digest, str) else ""


async def _clear_active_runner(todos_db: TodosDb, slug: str) -> None:
    state = await todos_db.read_state(slug)
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = None
    writer.state.manually_started = False
    await writer.commit(todos_db, slug)


async def _set_active_runner(
    todos_db: TodosDb,
    slug: str,
    session_id: str,
    *,
    lane: RunnerLane,
    manually_started: bool,
) -> None:
    """Write the driver link and its manual marker as one guarded mutation.

    ``active_runner`` and ``manually_started`` are always written together so a
    todo never carries a driver link without its origin marker.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = session_id
    writer.state.manually_started = manually_started
    if lane is RunnerLane.TASK_RUN:
        writer.state.lifecycle_phase = LifecyclePhase.TASK_RUNNING.value
    await writer.commit(todos_db, slug)


def _holder_slugs(rows: Sequence[TodoRow]) -> set[str]:
    """Structural-holder slugs derived in-memory from the loaded todo rows.

    Mirrors ``TodosDb._is_state_holder_slug`` (``group_slug == slug``,
    ``slug != slug``, ``status != "removed"``) over the already-fetched rows,
    avoiding an N+1 ``is_holder`` query per state-less row. A slug is a holder
    when a live child group-references it.
    """
    return {
        group_slug
        for row in rows
        if (group_slug := row["group_slug"]) and row["slug"] != group_slug and row["status"] != "removed"
    }


async def _load_todos(
    todos_db: TodosDb, db: Db, *, claimed_slugs: set[str] | None = None
) -> tuple[dict[str, RunnerTodo], list[str]]:
    rows = await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True)
    deps = await todos_db.load_deps()
    outstanding = claimed_slugs or set()
    holders = _holder_slugs(rows)
    loaded: dict[str, RunnerTodo] = {}
    reconciled: list[str] = []
    for row in rows:
        todo = await _read_runner_todo(todos_db, row)
        if todo is None:
            # A structural holder is deliberately state-less (read_state refuses
            # holders by design); never reconstitute it into a dispatchable
            # kind-less entry. A genuine non-holder state-less row keeps the
            # kind-discovery fallback below.
            if row["slug"] in holders:
                continue
            loaded[row["slug"]] = RunnerTodo(
                slug=row["slug"],
                status=row["status"],
                kind=None,
                lifecycle_phase=None,
                hold=False,
                active_runner=None,
            )
            continue
        todo = RunnerTodo(
            slug=todo.slug,
            status=todo.status,
            kind=todo.kind,
            lifecycle_phase=todo.lifecycle_phase,
            hold=todo.hold,
            active_runner=todo.active_runner,
            manually_started=todo.manually_started,
            after=tuple(deps.get(todo.slug, [])),
            schedule=todo.schedule,
            task_plan_digest=todo.task_plan_digest,
            task_approved=todo.task_approved,
            task_approved_digest=todo.task_approved_digest,
        )
        # Do not reconcile-clear a slug whose dispatch claim is still outstanding:
        # the spawn->live boot window is bridged by the claim lease, and the
        # session row may not yet read as live. Clearing here would race the next
        # pass into a duplicate dispatch (the storm this guard prevents).
        if todo.active_runner and todo.slug not in outstanding and not await _is_live_runner(db, todo.active_runner):
            await _clear_active_runner(todos_db, todo.slug)
            reconciled.append(todo.slug)
            todo = RunnerTodo(
                slug=todo.slug,
                status=todo.status,
                kind=todo.kind,
                lifecycle_phase=todo.lifecycle_phase,
                hold=todo.hold,
                active_runner=None,
                manually_started=False,
                after=todo.after,
                schedule=todo.schedule,
                task_plan_digest=todo.task_plan_digest,
                task_approved=todo.task_approved,
                task_approved_digest=todo.task_approved_digest,
            )
        loaded[todo.slug] = todo
    return loaded, reconciled


async def _live_active_runners(db: Db, todos: Mapping[str, RunnerTodo]) -> tuple[set[str], int]:
    """Resolve live driver session ids and the non-manual live-driver count.

    The full id set drives ALREADY_DRIVEN suppression (a manually-started todo is
    still driven and must never be auto-duplicated). The count excludes
    `manually_started` drivers because a human START or a headless adoption is
    never charged against the auto-dispatch concurrency cap.
    """
    live: set[str] = set()
    auto_count = 0
    for todo in todos.values():
        if todo.active_runner and await _is_live_runner(db, todo.active_runner):
            live.add(todo.active_runner)
            if not todo.manually_started:
                auto_count += 1
    return live, auto_count


async def dispatch_lifecycle_session(
    *,
    client: SessionRunner,
    todos_db: TodosDb,
    project_path: str,
    intent: DispatchIntent,
    origin: DispatchOrigin,
) -> str | None:
    """The single claim-guarded spawn primitive — the sole `active_runner` writer.

    The runner loop, an operator START, and headless adoption all flow through
    here so there is exactly one critical section and one writer of the driver
    link. The sequence is: acquire the `(slug, lane)` dispatch claim that bridges
    the boot gap, spawn the lifecycle session, then write `active_runner` paired
    with `manually_started` (derived from ``origin``) as one mutation.

    Returns the spawned session id, or ``None`` when the claim is already held by
    a concurrent pass (the caller treats this as a benign skip). On spawn failure
    the claim is released so a later pass can retry; on success it is retained,
    its lease covering the spawn->live window.
    """
    owner = f"lifecycle-runner:{intent.command}:{intent.slug}"
    acquired = await acquire_dispatch_claim(todos_db, slug=intent.slug, lane=intent.lane.value, owner=owner)
    if not acquired:
        return None
    try:
        kwargs: RunSessionArgs = {
            "command": intent.command,
            "project_path": project_path,
            "args": intent.slug,
            "detach": True,
        }
        if intent.thinking_mode is not None:
            kwargs["thinking_mode"] = intent.thinking_mode
        if intent.additional_context:
            kwargs["additional_context"] = intent.additional_context
        response = await client.run_session(**kwargs)
    except BaseException:
        # Spawn failed: drop the claim so a later pass can retry. On success the
        # claim is intentionally retained — its lease bridges the spawn->live gap
        # so the next pass sees the live active_runner and skips ALREADY_DRIVEN.
        await release_dispatch_claim(todos_db, slug=intent.slug, lane=intent.lane.value, owner=owner)
        raise
    await _set_active_runner(
        todos_db,
        intent.slug,
        response.session_id,
        lane=intent.lane,
        manually_started=origin.manually_started,
    )
    return response.session_id


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
    await _set_active_runner(todos_db, slug, session_id, lane=lane, manually_started=True)
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
    todos, _ = await _load_todos(todos_db, runtime_db)
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
    project_root = resolve_state_root(project_path)
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
    project_root = resolve_state_root(project_path)
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
            intent=_intent(slug, lane),
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
) -> ManualLifecycleSessionResult:
    """Claim an unheld slug in-process for a by-hand operator invocation.

    A manual invocation on an unheld todo (no live holder; earlier branches
    return ``ALREADY_DRIVEN`` when a different live session holds it) claims the
    slug in-process for the calling session — ``active_runner = caller``,
    ``manually_started = True`` — regardless of which slug the caller's session is
    bound to. The only binding requirement is a live caller session: a session id
    with no registry row returns ``NOT_BOUND``. The operation bridge then runs the
    state machine in the calling session; no separate orchestrator is dispatched.
    """
    project_root = resolve_state_root(project_path)
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
        elif todo.lifecycle_phase == LifecyclePhase.PREPARED.value:
            lane = RunnerLane.WORK
    if todo is not None and todo.active_runner == caller_session_id:
        await _set_active_runner(todos_db, slug, caller_session_id, lane=lane, manually_started=True)
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
    adopted = await adopt_headless_session(todos_db=todos_db, slug=slug, session_id=caller_session_id, lane=lane)
    if not adopted:
        return ManualLifecycleSessionResult(
            slug=slug,
            lane=lane,
            status=ManualLifecycleStatus.SKIPPED,
            reason=RunnerSkipReason.CLAIMED,
        )
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
    task_approval = _approval_from_state(state, "task_approved")
    todo = RunnerTodo(
        slug=slug,
        status="active",
        kind=kind,
        lifecycle_phase=lifecycle_phase,
        hold=state.get("hold") is True,
        active_runner=None,
        after=tuple(deps.get(slug, [])),
        schedule=await todos_db.get_schedule(slug),
        task_plan_digest=_artifact_digest_from_state(state, "task_plan"),
        task_approved=task_approval[0],
        task_approved_digest=task_approval[1],
    )
    prepared_slugs = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)
    lane, skip_reason = _resolve_kinded_dispatch(
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
    return _intent(slug, lane), None


def _manual_task_lane(todo: RunnerTodo) -> tuple[RunnerLane, RunnerSkipReason | None]:
    if not todo.task_plan_digest:
        return RunnerLane.TASK_PREPARE, None
    if not todo.task_approved or todo.task_approved_digest != todo.task_plan_digest:
        return RunnerLane.TASK_PREPARE, RunnerSkipReason.TASK_AUTHORIZATION_MISSING
    return RunnerLane.TASK_RUN, None


async def run_lifecycle_runner(
    project_path: str | Path,
    *,
    trigger: str = "manual",
    db: Db | None = None,
    client_factory: Callable[[], SessionRunner] = default_session_runner,
) -> RunnerResult:
    project_root = resolve_state_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_todos_db(project_root)
    claims = await list_dispatch_claims(todos_db)
    claimed_pairs = {(claim.slug, RunnerLane(claim.lane)) for claim in claims}
    claimed_slugs = {claim.slug for claim in claims}
    todos, reconciled = await _load_todos(todos_db, runtime_db, claimed_slugs=claimed_slugs)
    prepared_slugs = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered_slugs = await effective_delivered_slugs_for_dependencies(todos_db)
    workflow = config.workflow
    autostart = {
        KIND_FEATURE: workflow.autostart.feature,
        KIND_CHANGE: workflow.autostart.change,
        KIND_BUG: workflow.autostart.bug,
        KIND_TASK: workflow.autostart.task,
    }
    live_session_ids, auto_driver_count = await _live_active_runners(runtime_db, todos)
    orchestrator_owned_slugs = await live_orchestrator_owned_slugs(runtime_db, project_root)
    if workflow.runner is WorkflowRunnerMode.MANUAL:
        logger.info(
            "lifecycle runner frozen by manual mode",
            project_path=str(project_root),
            trigger=trigger,
            runner_mode=workflow.runner.value,
            evaluated=len(todos),
        )
    decision = decide_dispatches(
        todos,
        prepared_slugs=prepared_slugs,
        delivered_slugs=delivered_slugs,
        autostart=autostart,
        live_session_ids=live_session_ids,
        orchestrator_owned_slugs=orchestrator_owned_slugs,
        claimed=claimed_pairs,
        max_dispatch=workflow.max_todo_dispatch,
        live_driver_count=auto_driver_count,
        runner_mode=workflow.runner,
    )

    dispatched: list[DispatchIntent] = []
    woken: list[str] = []
    client = client_factory()
    await client.connect()
    try:
        woken = await wake_due_recurring_tasks(
            client=client,
            todos=todos,
            already_driven=decision.skips.get(RunnerSkipReason.ALREADY_DRIVEN, []),
            live_session_ids=live_session_ids,
            trigger=trigger,
        )
        for intent in decision.intents:
            session_id = await dispatch_lifecycle_session(
                client=client,
                todos_db=todos_db,
                project_path=str(project_root),
                intent=intent,
                origin=DispatchOrigin.RUNNER,
            )
            if session_id is None:
                decision.skip(RunnerSkipReason.CLAIMED, intent.slug)
                continue
            dispatched.append(intent)
    finally:
        await client.close()

    result = RunnerResult(
        project_path=str(project_root),
        trigger=trigger,
        evaluated=decision.evaluated,
        dispatched=dispatched,
        woken=woken,
        skips=decision.skips,
        reconciled=reconciled,
    )
    logger.info(
        "lifecycle runner pass",
        project_path=result.project_path,
        trigger=trigger,
        evaluated=result.evaluated,
        dispatched=[(intent.slug, intent.lane.value) for intent in dispatched],
        woken=woken,
        skip_counts={reason.value: len(slugs) for reason, slugs in result.skips.items()},
        skips={reason.value: slugs for reason, slugs in result.skips.items() if reason not in _TERMINAL_SKIP_REASONS},
        reconciled=reconciled,
    )
    return result


def project_path_from_event_payload(payload: Mapping[str, object]) -> str | None:
    project_path = payload.get("project_path")
    if isinstance(project_path, str) and project_path:
        return project_path
    return None


__all__ = [
    "DispatchIntent",
    "DispatchOrigin",
    "ManualLifecycleSessionResult",
    "ManualLifecycleStatus",
    "RunnerDecision",
    "RunnerLane",
    "RunnerResult",
    "RunnerSkipReason",
    "RunnerTodo",
    "adopt_headless_session",
    "adopt_manual_lifecycle_session",
    "decide_dispatches",
    "default_session_runner",
    "dispatch_lifecycle_session",
    "manual_start_lifecycle_session",
    "project_path_from_event_payload",
    "resolve_manual_dispatch_intent",
    "run_lifecycle_runner",
]
