"""State-derived lifecycle runner dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Protocol, Unpack

from instrukt_ai_logging import get_logger

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.cli.api_client import RunSessionArgs, TelecAPIClient
from teleclaude.config import WorkflowRunnerMode, config
from teleclaude.constants import COMMAND_ROLE_MAP, JobRole, SlashCommand, TodoStatus
from teleclaude.core.dates import task_schedule_due
from teleclaude.core.db import Db, get_db
from teleclaude.core.next_machine.dispatch_claims import (
    acquire_dispatch_claim,
    bind_dispatch_claim_session,
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
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id, live_orchestrator_owned_slugs
from teleclaude.core.next_machine.session_hold import reconcile_driver_ownership_for_session
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.project_root import resolve_project_root
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import HoldAuditState

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
_LIVE_TODO_STATUSES: frozenset[str] = frozenset({TodoStatus.ACTIVE.value, TodoStatus.ICEBOX.value})
_TERMINAL_TODO_STATUSES: frozenset[str] = frozenset({TodoStatus.DELIVERED.value, TodoStatus.REMOVED.value})


class _RunnerTodoRead(NamedTuple):
    todo: RunnerTodo | None
    allow_kind_discovery: bool
    current_status: str | None
    is_holder: bool


class SessionRunner(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO: ...
    async def end_session(self, session_id: str, computer: str) -> bool: ...


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


def _role_for_lane(lane: RunnerLane) -> tuple[str, JobRole]:
    """Resolve the ``(system_role, job)`` a directly-started driver of ``lane`` is born with.

    Reuses ``COMMAND_ROLE_MAP`` (the source of truth for born drivers) via the
    same lane-to-command resolution ``_command_for_lane`` uses, so an in-place
    adopted driver reaches exact born-driver parity. Every lane reachable
    through in-place adoption (PREPARE, WORK, TASK_PREPARE, TASK_RUN) carries a
    mapped command; a lane with no mapping is a contract violation and raises
    rather than leaving the caller with a silently empty role.
    """
    command_str, _, _ = _command_for_lane(lane)
    try:
        command = SlashCommand(command_str.lstrip("/"))
    except ValueError as exc:
        raise ValueError(f"no SlashCommand for lane {lane!r} (command={command_str!r})") from exc
    role_info = COMMAND_ROLE_MAP.get(command)
    if role_info is None:
        raise ValueError(f"no COMMAND_ROLE_MAP entry for lane {lane!r} (command={command!r})")
    return role_info


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
    # An invalidated plan re-enters preparation to derive its phase from current evidence.
    if lifecycle_phase_index(phase) >= lifecycle_phase_index(LifecyclePhase.PREPARED) and not todo.plan_review_cleared:
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
    claimed: set[tuple[str, str]] | None = None,
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
        if effective_hold(hold=todo.hold):
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


async def _read_runner_todo(todos_db: TodosDb, row: TodoRow) -> _RunnerTodoRead:
    status_read = await todos_db.read_status_and_state_by_id(row["id"])
    current_status = status_read.status
    state = status_read.state
    if current_status in _TERMINAL_TODO_STATUSES:
        active_runner = state.get("active_runner") if state is not None else None
        manually_started = state is not None and state.get("manually_started") is True
        return _RunnerTodoRead(
            todo=RunnerTodo(
                slug=row["slug"],
                status=current_status,
                kind=None,
                lifecycle_phase=None,
                hold=False,
                active_runner=active_runner if isinstance(active_runner, str) and active_runner else None,
                manually_started=manually_started,
                after=(),
                schedule=row["schedule"],
            ),
            allow_kind_discovery=False,
            current_status=current_status,
            is_holder=status_read.is_holder,
        )
    if current_status not in _LIVE_TODO_STATUSES:
        return _RunnerTodoRead(
            todo=None,
            allow_kind_discovery=False,
            current_status=current_status,
            is_holder=status_read.is_holder,
        )
    if status_read.is_holder:
        return _RunnerTodoRead(
            todo=None,
            allow_kind_discovery=False,
            current_status=current_status,
            is_holder=True,
        )
    if state is None:
        return _RunnerTodoRead(
            todo=None,
            allow_kind_discovery=True,
            current_status=current_status,
            is_holder=False,
        )
    return _RunnerTodoRead(
        todo=_todo_from_state(row, current_status, state),
        allow_kind_discovery=False,
        current_status=current_status,
        is_holder=False,
    )


def _todo_from_state(row: TodoRow, status: str, state: Mapping[str, StateValue]) -> RunnerTodo:
    kind = state.get("kind")
    phase = state.get("lifecycle_phase")
    active_runner = state.get("active_runner")
    task_plan_digest = _artifact_digest_from_state(state, "task_plan")
    task_approval = _approval_from_state(state, "task_approved")
    return RunnerTodo(
        slug=row["slug"],
        status=status,
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
        plan_review_cleared=_plan_review_cleared_from_state(state),
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


def _plan_review_cleared_from_state(state: Mapping[str, StateValue]) -> bool:
    plan_review = state.get("plan_review")
    return isinstance(plan_review, Mapping) and plan_review.get("cleared_by_substantive_drift") is True


async def _clear_active_runner(todos_db: TodosDb, row: TodoRow) -> None:
    state = await todos_db.read_state_by_id(row["id"])
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = None
    writer.state.manually_started = False
    await writer.commit_by_id(todos_db, row["id"])


async def _set_active_runner(
    todos_db: TodosDb,
    slug: str,
    session_id: str,
    *,
    lane: RunnerLane,
    manually_started: bool,
    release_hold: bool,
) -> None:
    """Write the driver link and its manual marker as one guarded mutation.

    ``active_runner`` and ``manually_started`` are always written together so a
    todo never carries a driver link without its origin marker. ``release_hold``
    is the caller-owned intent to clear a stored hold: true only for a fresh
    claim/start of a held unclaimed todo, false for a live owner's continuation.
    """
    state = await todos_db.read_state(slug)
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = session_id
    writer.state.manually_started = manually_started
    if release_hold:
        writer.state.hold = False
        writer.state.hold_audit = HoldAuditState()
    if lane is RunnerLane.TASK_RUN:
        writer.state.lifecycle_phase = LifecyclePhase.TASK_RUNNING.value
    await writer.commit(todos_db, slug)


async def _load_todos(
    todos_db: TodosDb, db: Db, *, claimed_slugs: set[str] | None = None
) -> tuple[dict[str, RunnerTodo], list[str]]:
    rows = sorted(
        await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True),
        key=lambda row: {"removed": 0, "delivered": 1, "icebox": 2, "active": 3}.get(row["status"], -1),
    )
    deps = await todos_db.load_deps()
    outstanding = claimed_slugs or set()
    loaded: dict[str, RunnerTodo] = {}
    reconciled: list[str] = []
    for row in rows:
        read = await _read_runner_todo(todos_db, row)
        todo = read.todo
        if todo is None:
            # A structural holder (status == 'holder') is deliberately
            # state-less by design; never reconstitute it into a dispatchable
            # kind-less entry. Holder-ness is read directly off the row's own
            # status, so it can never disagree with this skip.
            if read.is_holder:
                continue
            if not read.allow_kind_discovery:
                logger.warning(
                    "runner_todo_load_skipped_unclassifiable",
                    slug=row["slug"],
                    row_id=row["id"],
                    snapshot_status=row["status"],
                    current_status=read.current_status,
                )
                continue
            assert read.current_status is not None
            loaded[row["slug"]] = RunnerTodo(
                slug=row["slug"],
                status=read.current_status,
                kind=None,
                lifecycle_phase=None,
                hold=False,
                active_runner=None,
                schedule=row["schedule"],
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
            plan_review_cleared=todo.plan_review_cleared,
        )
        # Do not reconcile-clear a slug whose dispatch claim is still outstanding:
        # the spawn->live boot window is bridged by the claim lease, and the
        # session row may not yet read as live. Clearing here would race the next
        # pass into a duplicate dispatch (the storm this guard prevents).
        if todo.active_runner and todo.slug not in outstanding and not await _is_live_runner(db, todo.active_runner):
            await _clear_active_runner(todos_db, row)
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
                plan_review_cleared=todo.plan_review_cleared,
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
    runtime_db: Db,
    todos_db: TodosDb,
    project_path: str,
    intent: DispatchIntent,
    origin: DispatchOrigin,
) -> str | None:
    """The single claim-guarded spawn primitive — the sole `active_runner` writer.

    The runner loop, an operator START, and headless adoption all flow through
    here so there is exactly one critical section and one writer of the driver
    link. The sequence is: acquire the `(slug, lane)` dispatch claim that bridges
    the boot gap, spawn the lifecycle session, bind the claim to that session,
    then write `active_runner` paired with `manually_started` (derived from
    ``origin``) as one mutation.

    Returns the spawned session id, or ``None`` when the claim is already held by
    a concurrent pass (the caller treats this as a benign skip). On spawn failure
    the claim is released so a later pass can retry. On success it remains for
    the boot gap only: it is bound at handoff and reconciled when its driver
    ends. A spawned session that has lost its exact claim never becomes driver.
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
        bound = await bind_dispatch_claim_session(
            todos_db,
            slug=intent.slug,
            lane=intent.lane.value,
            owner=owner,
            session_id=response.session_id,
        )
    except BaseException:
        # Spawn or bind failed: drop the exact claim so a later pass can retry.
        # A successful bind retains the claim only through the boot gap; session
        # end reconciles it, while a lost bind ends the stale spawn below.
        await release_dispatch_claim(todos_db, slug=intent.slug, lane=intent.lane.value, owner=owner)
        raise
    if not bound:
        ended = await client.end_session(response.session_id, "local")
        if not ended:
            logger.error(
                "lifecycle spawn lost claim ownership and could not be ended",
                slug=intent.slug,
                lane=intent.lane.value,
                owner=owner,
                session_id=response.session_id,
                disposition="stale_spawn_end_failed",
            )
            return None
        logger.warning(
            "lifecycle spawn lost claim ownership",
            slug=intent.slug,
            lane=intent.lane.value,
            owner=owner,
            session_id=response.session_id,
            disposition="ended_stale_spawn",
        )
        return None
    await _set_active_runner(
        todos_db,
        intent.slug,
        response.session_id,
        lane=intent.lane,
        manually_started=origin.manually_started,
        release_hold=origin.manually_started,
    )
    session = await runtime_db.get_session(response.session_id)
    if session is not None and is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        reconciliation = await reconcile_driver_ownership_for_session(todos_db, response.session_id)
        logger.info(
            "terminal lifecycle spawn reconciled",
            session_id=response.session_id,
            released_claims=reconciliation.released_claims,
            cleared_slugs=",".join(reconciliation.cleared_slugs),
        )
    return response.session_id


async def run_lifecycle_runner(
    project_path: str | Path,
    *,
    trigger: str = "manual",
    db: Db | None = None,
    client_factory: Callable[[], SessionRunner] = default_session_runner,
) -> RunnerResult:
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_todos_db(project_root)
    claims = await list_dispatch_claims(todos_db)
    # Claim identity stays as stored. The claims table is shared with consumers
    # that own lanes the runner never dispatches — todo_artifact_authority's
    # diagnosis lease is one — and only runner-owned lanes participate in the
    # membership tests below. RunnerLane is a StrEnum, so those tests match a
    # stored lane string without conversion.
    claimed_pairs = {(claim.slug, claim.lane) for claim in claims}
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
    client = client_factory()
    await client.connect()
    try:
        for intent in decision.intents:
            session_id = await dispatch_lifecycle_session(
                client=client,
                runtime_db=runtime_db,
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
        skips=decision.skips,
        reconciled=reconciled,
    )
    logger.info(
        "lifecycle runner pass",
        project_path=result.project_path,
        trigger=trigger,
        evaluated=result.evaluated,
        dispatched=[(intent.slug, intent.lane.value) for intent in dispatched],
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


# Shared dispatch primitives consumed by the manual-start lane (manual_start.py),
# an internal extraction of this subsystem. Declared here as the narrow public
# interface so the lane never reaches into module-private helpers.
approval_from_state = _approval_from_state
artifact_digest_from_state = _artifact_digest_from_state
plan_review_cleared_from_state = _plan_review_cleared_from_state
command_for_lane = _command_for_lane
role_for_lane = _role_for_lane
make_intent = _intent
load_runner_todos = _load_todos
resolve_kinded_dispatch = _resolve_kinded_dispatch
set_active_runner = _set_active_runner


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
    "approval_from_state",
    "artifact_digest_from_state",
    "command_for_lane",
    "decide_dispatches",
    "default_session_runner",
    "dispatch_lifecycle_session",
    "load_runner_todos",
    "make_intent",
    "plan_review_cleared_from_state",
    "project_path_from_event_payload",
    "resolve_kinded_dispatch",
    "role_for_lane",
    "run_lifecycle_runner",
    "set_active_runner",
]
