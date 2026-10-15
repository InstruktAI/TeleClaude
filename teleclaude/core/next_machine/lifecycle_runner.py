"""State-derived lifecycle runner dispatch."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Final, NamedTuple

from instrukt_ai_logging import get_logger

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
    ApprovalGate,
    effective_hold,
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
    is_live_session_id,
    live_orchestrator_owned_slugs,
    start_in_flight,
)
from teleclaude.core.next_machine.session_hold import reconcile_driver_ownership_for_session
from teleclaude.core.next_machine.start_reservation import give_back, record_reservation
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter, commit_on_current
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.core.workflow_machine.dependencies import delivered_slugs as delivered_slugs_of
from teleclaude.core.workflow_machine.dependencies import prepared_slugs as prepared_slugs_of
from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import awaits_readable_head, read_phase
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import WorkItemStateRead as TodoStatusStateRead
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import HoldAuditState, TodoState
from teleclaude.types.workflow_record import Phase

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
    if todo.item_phase is None:
        return None, RunnerSkipReason.UNKNOWN_PHASE
    if todo.head_unreadable:
        return None, RunnerSkipReason.HEAD_UNREADABLE
    phase = Phase(todo.item_phase)
    skipped = _PHASE_SKIPS.get(phase)
    if skipped is not None:
        return None, skipped
    if phase is Phase.PREPARATION:
        # Preparation always runs regardless of autostart; agents park at the human gates themselves.
        lane = RunnerLane.PREPARE
        unmet = [dep for dep in todo.after if dep not in prepared_slugs]
    else:
        # A prepared item, or one in work (a stale stamp reads as work), enters the execution runtime.
        if not _autostart_enabled(kind, autostart):
            return None, RunnerSkipReason.POLICY_DISABLED
        lane = RunnerLane.WORK
        unmet = [dep for dep in todo.after if dep not in delivered_slugs]
    if unmet:
        return None, RunnerSkipReason.DEPENDENCY_BLOCKED
    return lane, None


_PHASE_SKIPS: Final[Mapping[Phase, RunnerSkipReason]] = {
    Phase.WAITING: RunnerSkipReason.WAITING,
    Phase.READY: RunnerSkipReason.READY,
    Phase.DESIGN: RunnerSkipReason.DESIGN,
    Phase.DELIVERED: RunnerSkipReason.DELIVERED,
}


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


def _creative_approval_pending(model: TodoState) -> bool:
    """Whether a creative approval is pending; the retired PRD human approval gate no longer holds an item back."""
    gate = pending_approval_gate(model)
    return gate is not None and gate is not ApprovalGate.PRD


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
        human_approval_pending=_creative_approval_pending(model),
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


_LIVE_ROW_STATUSES: Final = frozenset({"active", "icebox"})
LINK_SKIPPED_LOG: Final = "lifecycle runner: the started session was not linked, the row is held by another session"


class LifecycleLinkLost(Exception):
    """The row has another owner, so no driver was started; the winning owner is named."""

    def __init__(self, slug: str, owner: str) -> None:
        super().__init__(slug, owner)
        self.slug = slug
        self.owner = owner


async def _release_reserved_link(todos_db: WorkflowStore, slug: str, session_id: str) -> None:
    """Withdraw the link reserved for a session that was never created, only while it is still that session\'s.

    What the reservation replaced (a cleared hold, the task phase) goes back with it, each only while the row still
    carries the reservation\'s mark, so a refused start leaves the row as it found it and a later operator change stands.
    """

    def change(writer: StateWriter) -> None:
        if writer.state.active_runner != session_id:
            return
        writer.state.active_runner = None
        writer.state.manually_started = False
        give_back(writer, session_id, accepted=False)

    with suppress(StateMutationError):  # the item left the store: there is no row to give anything back to
        await commit_on_current(todos_db, slug, change)


async def _confirm_reserved_start(todos_db: WorkflowStore, slug: str, session_id: str) -> None:
    """Settle the reservation\'s mark once the start is accepted; any other audit is left alone."""

    def change(writer: StateWriter) -> None:
        give_back(writer, session_id, accepted=True)

    with suppress(StateMutationError):  # the item left the store: there is no mark left to clear
        await commit_on_current(todos_db, slug, change)


class LifecycleItemUnavailable(Exception):
    """The item is missing, removed or delivered, so no driver link could be committed and no session was started."""

    def __init__(self, slug: str) -> None:
        super().__init__(slug)
        self.slug = slug


class LinkSkipped(Exception):
    """The row was claimed by another session before the started driver could be linked; nothing was written."""


async def _clear_active_runner(
    todos_db: WorkflowStore, row: TodoRow, expected_runner: str, *, session_exists: bool
) -> None:
    """Clear the dead driver's link, and only that link: a replacement that claimed the row meanwhile is left alone.

    A link whose session never came to exist was a reservation that no start accepted, so what it replaced goes back
    with it; a session that exists was accepted, and only the reservation's mark is settled.
    """

    def change(writer: StateWriter) -> None:
        if writer.state.active_runner != expected_runner:
            return
        writer.state.active_runner = None
        writer.state.manually_started = False
        give_back(writer, expected_runner, accepted=session_exists)

    if row["status"] in _LIVE_ROW_STATUSES:
        await commit_on_current(todos_db, row["slug"], change)
        return
    state = await todos_db.read_state_by_id(row["id"])
    if state is None:
        return
    writer = StateWriter(state)
    change(writer)
    await writer.commit_by_id(todos_db, row["id"])


async def _set_active_runner(
    todos_db: WorkflowStore,
    slug: str,
    session_id: str,
    *,
    lane: RunnerLane,
    manually_started: bool,
    release_hold: bool,
    reserve: bool = False,
    require_row: bool = False,
) -> str:
    """Write the driver link and its manual marker as one guarded mutation; the winning owner when the row has one.

    ``reserve`` records what the same mutation replaced (a cleared hold, the task phase) on the row, so a start that is
    never accepted can give it back, also after a crash.
    ``require_row`` makes a missing item an outcome of its own (``LifecycleItemUnavailable``) rather than an empty
    answer a caller could read as linked: a start that must have its link committed before it begins needs the row.

    ``active_runner`` and ``manually_started`` are always written together so a
    todo never carries a driver link without its origin marker. ``release_hold``
    is the caller-owned intent to clear a stored hold: true only for a fresh
    claim/start of a held unclaimed todo, false for a live owner's continuation.
    """
    if await todos_db.read_state(slug) is None:
        if require_row:
            raise LifecycleItemUnavailable(slug)
        return ""

    def change(writer: StateWriter) -> None:
        owner = writer.state.active_runner
        if owner and owner != session_id:
            raise LinkSkipped(owner)
        writer.state.active_runner = session_id
        writer.state.manually_started = manually_started
        if reserve:
            record_reservation(writer, session_id, clears_hold=release_hold, task_run=lane is RunnerLane.TASK_RUN)
            return
        if release_hold:
            writer.state.hold = False
            writer.state.hold_audit = HoldAuditState()
        if lane is RunnerLane.TASK_RUN:
            writer.state.lifecycle_phase = LifecyclePhase.TASK_RUNNING

    try:
        await commit_on_current(todos_db, slug, change)
    except LinkSkipped as moved:
        winner = str(moved)
        logger.warning(LINK_SKIPPED_LOG, slug=slug, started=session_id, owner=winner)
        return winner
    except StateMutationError as vanished:
        if require_row:
            raise LifecycleItemUnavailable(slug) from vanished
        raise
    return ""


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
        todo = replace(todo, after=tuple(deps.get(todo.slug, [])))
        state = states_by_slug.get(todo.slug)
        if state is not None and todo.kind != KIND_TASK:
            raw_state = status_reads[row["id"]].state or {}
            lane = await resolve_lane(todos_db, str(todos_db.project_root), todo.slug, raw_state, state)
            reading = read_phase(state, lane)
            todo = replace(
                todo,
                item_phase=reading.phase.value if reading.phase is not None else None,
                head_unreadable=awaits_readable_head(state, lane),
            )
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
                todo = replace(todo, dependency_drift_pending_on=tuple(sorted(moved_dependencies)))
        if todo.active_runner and not await _is_live_runner(db, todo.active_runner):
            await _clear_active_runner(
                todos_db, row, todo.active_runner, session_exists=await db.get_session(todo.active_runner) is not None
            )
            reconciled.append(todo.slug)
            todo = replace(todo, active_runner=None, manually_started=False)
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
    runtime_db: Db,
    todos_db: WorkflowStore,
    project_path: str,
    intent: DispatchIntent,
    origin: DispatchOrigin,
) -> str:
    """Start a lifecycle driver under a session identity chosen first and linked before the session is created.

    The link is reserved on the item before the session exists, in the one conditional write that decides who owns the
    row: the loser starts nothing and learns the winner, so no accepted start can be left unlinked, and a crash after
    the reservation leaves a link to a session that never was, which the next pass clears like any dead driver link. The
    session is then started in process under that identity through the platform\'s one session-run path.
    """
    from teleclaude.api.sessions_actions_routes import (  # noqa: PLC0415 - deferred cycle: the routes read this package
        run_platform_session,
    )
    from teleclaude.api_models import RunSessionRequest  # noqa: PLC0415 - deferred cycle: the models read this package

    session_id = str(uuid.uuid4())
    with start_in_flight(session_id):
        winner = await _set_active_runner(
            todos_db,
            intent.slug,
            session_id,
            lane=intent.lane,
            manually_started=origin.manually_started,
            release_hold=origin.manually_started,
            reserve=True,
            require_row=True,
        )
        if winner:
            raise LifecycleLinkLost(intent.slug, winner)
        request = RunSessionRequest(
            command=intent.command,
            args=intent.slug,
            project=project_path,
            detach=True,
            additional_context=intent.additional_context,
        )
        try:
            await run_platform_session(request, session_id=session_id)
        except BaseException:
            if await runtime_db.get_session(session_id) is None:
                await _release_reserved_link(todos_db, intent.slug, session_id)
            else:
                await _confirm_reserved_start(todos_db, intent.slug, session_id)
            raise
        await _confirm_reserved_start(todos_db, intent.slug, session_id)
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


_ITEM_LANES: Final = frozenset({RunnerLane.PREPARE, RunnerLane.WORK})
_REFUSED_LOG: Final = "lifecycle runner: the driver request was refused"
_REQUEST_FAILED_LOG: Final = "lifecycle runner: the driver request failed"


async def _request_item_driver(project_path: str, intent: DispatchIntent) -> bool:
    """Ask the lifecycle machine to start the driver of a prepare or work intent; False when it refuses or fails.

    The request is recorded and returns without waiting for the driver to claim; the driver claims for itself.
    """
    from teleclaude.core.workflow_machine.entry import (  # noqa: PLC0415 - deferred cycle: the machine reads this package
        EntryRefused,
        EntryRequest,
        EntryVerb,
        StartOrigin,
        enter,
    )

    verb = EntryVerb.PREPARE if intent.lane is RunnerLane.PREPARE else EntryVerb.WORK
    try:
        await enter(
            EntryRequest(
                project_root=project_path,
                item=intent.slug,
                verb=verb,
                caller_session_id="",
                wait_for_claim=False,
                origin=StartOrigin.RUNNER,
            )
        )
    except EntryRefused as refusal:
        logger.info(_REFUSED_LOG, slug=intent.slug, lane=intent.lane.value, reason=str(refusal))
        return False
    except Exception:  # supervision boundary: one failing request must not stop the pass
        logger.exception(_REQUEST_FAILED_LOG, slug=intent.slug, lane=intent.lane.value)
        return False
    return True


async def run_lifecycle_runner(
    project_path: str | Path,
    *,
    trigger: str = "manual",
    db: Db | None = None,
) -> RunnerResult:
    project_root = resolve_project_root(project_path)
    runtime_db = db or await get_db()
    todos_db = await get_workflow_store(project_root)
    todos, reconciled = await _load_todos(todos_db, runtime_db)
    prepared_slugs = await prepared_slugs_of(todos_db)
    delivered_slugs = await delivered_slugs_of(todos_db)
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
    for intent in decision.intents:
        if intent.lane in _ITEM_LANES:
            if await _request_item_driver(str(project_root), intent):
                dispatched.append(intent)
            continue
        try:
            await dispatch_lifecycle_session(
                runtime_db=runtime_db,
                todos_db=todos_db,
                project_path=str(project_root),
                intent=intent,
                origin=DispatchOrigin.RUNNER,
            )
        except (LifecycleLinkLost, LifecycleItemUnavailable):
            continue
        dispatched.append(intent)

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
    "LifecycleItemUnavailable",
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
