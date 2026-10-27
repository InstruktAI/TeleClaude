"""State-derived lifecycle runner dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Protocol, Unpack

from instrukt_ai_logging import get_logger

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.api_session_args import RunSessionArgs
from teleclaude.config._models import WorkflowRunnerMode
from teleclaude.config.machine import config
from teleclaude.constants import TodoStatus
from teleclaude.context_selector import resolve_snippet_meta
from teleclaude.core.dates import task_schedule_due
from teleclaude.core.db import Db, get_db
from teleclaude.core.next_machine.git_ops import (
    DRIFT_PENDING,
    build_dependency_artifact_snapshot,
    dependency_artifact_evidence,
    derive_dependency_artifact_drift,
)
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_CHANGE, KIND_FEATURE, KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lanes import LANE_ENTRY_PROCEDURES
from teleclaude.core.next_machine.lifecycle import (
    coerce_lifecycle_phase,
    effective_hold,
    is_in_work_lane,
    pending_approval_gate,
    plan_review_current,
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
    find_accepted_lifecycle_start,
    is_live_session_id,
    live_orchestrator_owned_slugs,
)
from teleclaude.core.next_machine.session_hold import reconcile_driver_ownership_for_session
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import WorkItemStateRead as TodoStatusStateRead
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import HoldAuditState, TodoState

logger = get_logger(__name__)

_LANE_ROLE_UNDECLARED_TEMPLATE = "lane {lane!r}: entry procedure {procedure} declares no role"
_RUNNER_REPREPARE_EVENT = "todo_runner_routed_to_prepare"
_RUNNER_REPREPARE_MESSAGE = "todo runner routed to prepare"
_RUNNER_REPREPARE_OUTCOME = "prepare"
_RUNNER_REPREPARE_REASON = "plan_review_not_current"
_RUNNER_DEPENDENCY_ARTIFACT_DRIFT_REASON = "dependency_artifact_drift_pending"


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
    current_status: str | None
    is_holder: bool


class SessionRunner(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO: ...


def default_session_runner() -> SessionRunner:
    return TelecAPIClient(daemon_credential=True)


def _command_for_lane(lane: RunnerLane) -> tuple[str, str]:
    """The entry procedure ID a driver of ``lane`` is started through, with its additional context."""
    return LANE_ENTRY_PROCEDURES[lane].value, ""


def _role_for_lane(lane: RunnerLane, project_root: Path) -> str:
    """Resolve the catalog role a directly-started driver of ``lane`` is born with.

    The role is the one the lane's entry procedure declares, so an in-place adopted driver reaches exact
    born-driver parity. A lane whose entry procedure declares no role is a contract violation and raises
    rather than leaving the caller with a silently empty role.
    """
    procedure_id, _ = _command_for_lane(lane)
    snippet = resolve_snippet_meta(procedure_id, project_root=project_root)
    declarations = snippet.entry.declarations if snippet is not None else None
    if declarations is None:
        raise ValueError(_LANE_ROLE_UNDECLARED_TEMPLATE.format(lane=lane, procedure=procedure_id))
    return declarations.role.name.value


def _intent(slug: str, lane: RunnerLane) -> DispatchIntent:
    command, additional_context = _command_for_lane(lane)
    return DispatchIntent(
        slug=slug,
        lane=lane,
        command=command,
        additional_context=additional_context,
    )


def _autostart_enabled(kind: TodoKind, autostart: Mapping[TodoKind, bool]) -> bool:
    return bool(autostart.get(kind, False))


def _pending_approval_gate_for_runner(todo: RunnerTodo) -> bool:
    return todo.human_approval_pending


def _resolve_kinded_dispatch(
    todo: RunnerTodo,
    kind: TodoKind,
    *,
    prepared_slugs: set[str],
    delivered_slugs: set[str],
    autostart: Mapping[TodoKind, bool],
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
    if phase == LifecyclePhase.FINALIZE_READY and todo.plan_review_current:
        return None, RunnerSkipReason.FINALIZE_READY
    if is_in_work_lane(phase, plan_review_is_current=todo.plan_review_current):
        if todo.dependency_drift_pending_on:
            # Re-derive a prepared dependent before its work runtime resumes.
            unmet = [dep for dep in todo.after if dep not in prepared_slugs]
            lane = RunnerLane.PREPARE
        else:
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
    autostart: Mapping[TodoKind, bool],
    live_session_ids: set[str],
    orchestrator_owned_slugs: set[str] | None = None,
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
        if _at_capacity():
            decision.skip(RunnerSkipReason.AT_CAPACITY, slug)
            continue
        if lane is RunnerLane.PREPARE and todo.dependency_drift_pending_on:
            logger.info(
                _RUNNER_REPREPARE_MESSAGE,
                event=_RUNNER_REPREPARE_EVENT,
                outcome=_RUNNER_REPREPARE_OUTCOME,
                reason=_RUNNER_DEPENDENCY_ARTIFACT_DRIFT_REASON,
                slug=slug,
                lifecycle_phase=todo.lifecycle_phase or "",
                dependencies=sorted(todo.dependency_drift_pending_on),
            )
        elif (
            lane is RunnerLane.PREPARE and coerce_lifecycle_phase(todo.lifecycle_phase) is LifecyclePhase.FINALIZE_READY
        ):
            logger.info(
                _RUNNER_REPREPARE_MESSAGE,
                event=_RUNNER_REPREPARE_EVENT,
                outcome=_RUNNER_REPREPARE_OUTCOME,
                reason=_RUNNER_REPREPARE_REASON,
                slug=slug,
                lifecycle_phase=LifecyclePhase.FINALIZE_READY.value,
                current_plan_digest=todo.current_plan_digest,
                reviewed_plan_digest=todo.reviewed_plan_digest,
            )
        decision.intents.append(_intent(slug, lane))
    return decision


async def _is_live_runner(db: Db, session_id: str | None) -> bool:
    return bool(session_id and await is_live_session_id(db, session_id))


def _read_runner_todo(row: TodoRow, status_read: TodoStatusStateRead) -> _RunnerTodoRead:
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
                human_approval_pending=False,
                hold=False,
                active_runner=active_runner if isinstance(active_runner, str) and active_runner else None,
                manually_started=manually_started,
                after=(),
                schedule=row["schedule"],
            ),
            current_status=current_status,
            is_holder=status_read.is_structural_group_holder,
        )
    if current_status not in _LIVE_TODO_STATUSES:
        return _RunnerTodoRead(
            todo=None,
            current_status=current_status,
            is_holder=status_read.is_structural_group_holder,
        )
    if status_read.is_structural_group_holder:
        return _RunnerTodoRead(
            todo=None,
            current_status=current_status,
            is_holder=True,
        )
    if state is None:
        return _RunnerTodoRead(
            todo=None,
            current_status=current_status,
            is_holder=False,
        )
    return _RunnerTodoRead(
        todo=_todo_from_state(row, current_status, state),
        current_status=current_status,
        is_holder=False,
    )


def _todo_from_state(row: TodoRow, status: str, state: Mapping[str, StateValue]) -> RunnerTodo:
    model = TodoState.model_validate(state)
    active_runner = state.get("active_runner")
    task_plan_digest = _artifact_digest_from_state(state, "task_plan")
    task_approval = _approval_from_state(state, "task_approved")
    return RunnerTodo(
        slug=row["slug"],
        status=status,
        kind=model.kind,
        lifecycle_phase=model.lifecycle_phase.value,
        human_approval_pending=pending_approval_gate(model) is not None,
        hold=state.get("hold") is True,
        active_runner=active_runner if isinstance(active_runner, str) and active_runner else None,
        manually_started=state.get("manually_started") is True,
        after=(),
        schedule=row["schedule"],
        task_plan_digest=task_plan_digest,
        task_approved=task_approval[0],
        task_approved_digest=task_approval[1],
        plan_review_current=plan_review_current(model),
        current_plan_digest=model.artifacts.implementation_plan.digest,
        reviewed_plan_digest=model.plan_review.reviewed_target_digest,
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


async def _clear_active_runner(todos_db: WorkflowStore, row: TodoRow) -> None:
    state = await todos_db.read_state_by_id(row["id"])
    if state is None:
        return
    writer = StateWriter(state)
    writer.state.active_runner = None
    writer.state.manually_started = False
    await writer.commit_by_id(todos_db, row["id"])


async def _set_active_runner(
    todos_db: WorkflowStore,
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
        writer.state.lifecycle_phase = LifecyclePhase.TASK_RUNNING
    await writer.commit(todos_db, slug)


async def _load_todos(todos_db: WorkflowStore, db: Db) -> tuple[dict[str, RunnerTodo], list[str]]:
    rows = sorted(
        await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True),
        key=lambda row: {"removed": 0, "delivered": 1, "icebox": 2, "active": 3}.get(row["status"], -1),
    )
    status_reads = await todos_db.read_status_and_states_by_id([row["id"] for row in rows])
    deps = await todos_db.load_deps()
    states_by_slug: dict[str, TodoState | None] = {}
    statuses_by_slug: dict[str, TodoStatus] = {}
    for row in rows:
        status_read = status_reads.get(
            row["id"],
            TodoStatusStateRead(status=None, state=None, is_structural_group_holder=False),
        )
        if status_read.status is not None:
            statuses_by_slug[row["slug"]] = TodoStatus(status_read.status)
        states_by_slug[row["slug"]] = (
            TodoState.model_validate(status_read.state) if status_read.state is not None else None
        )
    loaded: dict[str, RunnerTodo] = {}
    reconciled: list[str] = []
    for row in rows:
        status_read = status_reads.get(
            row["id"],
            TodoStatusStateRead(status=None, state=None, is_structural_group_holder=False),
        )
        read = _read_runner_todo(row, status_read)
        todo = read.todo
        if todo is None:
            # A structural holder (status == 'holder') is deliberately
            # state-less by design; never reconstitute it into a dispatchable
            # todo entry. Holder-ness is read directly off the row's own
            # status, so it can never disagree with this skip.
            if read.is_holder:
                continue
            if read.current_status in _LIVE_TODO_STATUSES and status_read.state is None:
                logger.warning(
                    "runner_todo_load_skipped_missing_state",
                    slug=row["slug"],
                    row_id=row["id"],
                    snapshot_status=row["status"],
                    current_status=read.current_status,
                )
            continue
        todo = RunnerTodo(
            slug=todo.slug,
            status=todo.status,
            kind=todo.kind,
            lifecycle_phase=todo.lifecycle_phase,
            human_approval_pending=todo.human_approval_pending,
            hold=todo.hold,
            active_runner=todo.active_runner,
            manually_started=todo.manually_started,
            after=tuple(deps.get(todo.slug, [])),
            schedule=todo.schedule,
            task_plan_digest=todo.task_plan_digest,
            task_approved=todo.task_approved,
            task_approved_digest=todo.task_approved_digest,
            plan_review_current=todo.plan_review_current,
            current_plan_digest=todo.current_plan_digest,
            reviewed_plan_digest=todo.reviewed_plan_digest,
            dependency_drift_pending_on=todo.dependency_drift_pending_on,
        )
        state = states_by_slug.get(todo.slug)
        if state is not None and todo.kind in {KIND_FEATURE, KIND_CHANGE, KIND_BUG}:
            dependency_snapshot = build_dependency_artifact_snapshot(
                [
                    (dep_slug, statuses_by_slug[dep_slug])
                    for dep_slug in deps.get(todo.slug, [])
                    if dep_slug in statuses_by_slug
                ],
                states_by_slug.get,
            )
            if derive_dependency_artifact_drift(state, dependency_snapshot) == DRIFT_PENDING:
                _, moved_dependencies = dependency_artifact_evidence(
                    state.artifacts.implementation_plan.dependency_artifact_digests,
                    dependency_snapshot,
                )
                todo = RunnerTodo(
                    slug=todo.slug,
                    status=todo.status,
                    kind=todo.kind,
                    lifecycle_phase=todo.lifecycle_phase,
                    human_approval_pending=todo.human_approval_pending,
                    hold=todo.hold,
                    active_runner=todo.active_runner,
                    manually_started=todo.manually_started,
                    after=todo.after,
                    schedule=todo.schedule,
                    task_plan_digest=todo.task_plan_digest,
                    task_approved=todo.task_approved,
                    task_approved_digest=todo.task_approved_digest,
                    plan_review_current=todo.plan_review_current,
                    current_plan_digest=todo.current_plan_digest,
                    reviewed_plan_digest=todo.reviewed_plan_digest,
                    dependency_drift_pending_on=tuple(sorted(moved_dependencies)),
                )
        if todo.active_runner and not await _is_live_runner(db, todo.active_runner):
            await _clear_active_runner(todos_db, row)
            reconciled.append(todo.slug)
            todo = RunnerTodo(
                slug=todo.slug,
                status=todo.status,
                kind=todo.kind,
                lifecycle_phase=todo.lifecycle_phase,
                human_approval_pending=todo.human_approval_pending,
                hold=todo.hold,
                active_runner=None,
                manually_started=False,
                after=todo.after,
                schedule=todo.schedule,
                task_plan_digest=todo.task_plan_digest,
                task_approved=todo.task_approved,
                task_approved_digest=todo.task_approved_digest,
                plan_review_current=todo.plan_review_current,
                current_plan_digest=todo.current_plan_digest,
                reviewed_plan_digest=todo.reviewed_plan_digest,
                dependency_drift_pending_on=todo.dependency_drift_pending_on,
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
    todos_db: WorkflowStore,
    project_path: str,
    intent: DispatchIntent,
    origin: DispatchOrigin,
) -> str:
    """Start a lifecycle driver and record its ownership directly.

    The start is idempotent per todo and lane: a repeated dispatch records the driver an earlier
    dispatch already started instead of starting another (``event-consumers``, Retained occurrences).
    """
    # An earlier dispatch whose ``active_runner`` record failed left an accepted, unrecorded start.
    # Recording that session is the same direct adoption ADR-0078 sanctions, so re-entry completes the
    # interrupted operation rather than creating a second orchestrator. The session is found by the
    # subject its creation wrote (lane role, slug, project); no reservation or pre-ownership state exists.
    session_id = await find_accepted_lifecycle_start(
        runtime_db,
        project_path,
        intent.slug,
        _role_for_lane(intent.lane, Path(project_path)),
    )
    if session_id is None:
        kwargs: RunSessionArgs = {
            "command": intent.command,
            "project_path": project_path,
            "args": intent.slug,
            "detach": True,
        }
        if intent.additional_context:
            kwargs["additional_context"] = intent.additional_context
        response = await client.run_session(**kwargs)
        session_id = response.session_id
    await _set_active_runner(
        todos_db,
        intent.slug,
        session_id,
        lane=intent.lane,
        manually_started=origin.manually_started,
        release_hold=origin.manually_started,
    )
    session = await runtime_db.get_session(session_id)
    if session is not None and is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        reconciliation = await reconcile_driver_ownership_for_session(todos_db, session_id)
        logger.info(
            "terminal lifecycle spawn reconciled",
            session_id=session_id,
            cleared_slugs=",".join(reconciliation.cleared_slugs),
        )
    return session_id


async def run_lifecycle_runner(
    project_path: str | Path,
    *,
    trigger: str = "manual",
    db: Db | None = None,
    client_factory: Callable[[], SessionRunner] = default_session_runner,
) -> RunnerResult:
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_workflow_store(project_root)
    todos, reconciled = await _load_todos(todos_db, runtime_db)
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
        max_dispatch=workflow.max_todo_dispatch,
        live_driver_count=auto_driver_count,
        runner_mode=workflow.runner,
    )

    dispatched: list[DispatchIntent] = []
    client = client_factory()
    await client.connect()
    try:
        for intent in decision.intents:
            await dispatch_lifecycle_session(
                client=client,
                runtime_db=runtime_db,
                todos_db=todos_db,
                project_path=str(project_root),
                intent=intent,
                origin=DispatchOrigin.RUNNER,
            )
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
plan_review_current_from_state = plan_review_current
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
    "plan_review_current_from_state",
    "project_path_from_event_payload",
    "resolve_kinded_dispatch",
    "role_for_lane",
    "run_lifecycle_runner",
    "set_active_runner",
]
