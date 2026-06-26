"""Functional tests for the state-derived lifecycle runner."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest
from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.sessions_actions_routes import _prepare_run_session
from teleclaude.api_models import CreateSessionResponseDTO, RunSessionRequest
from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.config import WorkflowRunnerMode
from teleclaude.config import config as tc_config
from teleclaude.constants import (
    ARTIFACT_PRD,
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
    WORKTREE_DIR,
    DriverLaunchClass,
)
from teleclaude.core import db as db_mod
from teleclaude.core import session_listeners as session_listeners_mod
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.next_machine import lifecycle_runner as runner_mod
from teleclaude.core.next_machine import session_hold
from teleclaude.core.next_machine.dispatch_claims import list_dispatch_claims
from teleclaude.core.next_machine.lifecycle import ApprovalGate, effective_hold, pending_approval_gate
from teleclaude.core.next_machine.lifecycle_runner import (
    DispatchIntent,
    DispatchOrigin,
    ManualLifecycleStatus,
    RunnerLane,
    RunnerSkipReason,
    RunnerTodo,
    adopt_headless_session,
    adopt_manual_lifecycle_session,
    decide_dispatches,
    dispatch_lifecycle_session,
    guard_driver_start,
    manual_start_lifecycle_session,
    resolve_manual_dispatch_intent,
    run_lifecycle_runner,
)
from teleclaude.core.next_machine.runtime.clock import SCHEDULER_TICK_MINUTE
from teleclaude.core.next_machine.runtime.sessions import (
    live_orchestrator_owned_slugs,
    live_orchestrator_owner,
)
from teleclaude.core.next_machine.session_hold import (
    clear_active_runner_for_session_end,
    hold_todo_for_manual_session_close,
    notify_runner_of_gate_approval,
)
from teleclaude.core.operations.service import (
    OPERATION_KIND_TASK_RUN,
    OPERATION_KIND_TODO_WORK,
    OperationsService,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.core.todos_db._exceptions import ClaimConflict
from teleclaude.events.cartridges import lifecycle_router
from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.schemas import register_all
from teleclaude.git import Repo
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/domain/workflow"
_STAMPING_SPEC = "project/spec/feature/workflow/state-stamping"
_VERSIONING_SPEC = "project/spec/feature/workflow/artifact-versioning"
_PREPARE_SPEC = "project/spec/feature/workflow/prepare-state-machine"
_FEATURE = "feature"
_CHANGE = "change"
_TASK = "task"
_PARENT = "parent"
_CHILD = "child"
_WORK_SLUG = "work-a"
_LIVE_SLUG = "live-a"
_OTHER_SLUG = "other-a"
_OTHER_WORKTREE_SLUG = "unrelated-feature"
_STALE_SESSION = "stale-session"
_LIVE_SESSION = "live-session"
_ORCH_SESSION = "orch-session"
_CROSS_PROJECT_SESSION = "cross-project"
_SPAWN_SESSION = "spawn-1"
_CLOSE_HOLD_SESSION = "close-hold-session"
_CLOSE_END_SESSION = "close-end-session"
_NEXT_WORK = "/next-work"
_NEXT_PREPARE = "/next-prepare"
_NEXT_PREPARE_TASK = "/next-prepare-task"
_NEXT_RUN_TASK = "/next-run-task"
_CONTINUED = "continued"
_HOLD_SOURCE_SESSION_CLOSE = "session_close"
_DOMAIN = "software-development"
_SOURCE = "test"
_DELIVERY_COMMIT = "abc123def456789"
_SYNC_DELIVERY_COMMIT = "789def456abc123"
_WAKE_EVENTS = (
    "workflow.todo.created",
    "workflow.todo.delivered",
    "workflow.todo.phase_advanced",
    "workflow.todo.updated",
    "workflow.roadmap.entry_moved",
    "config.effective.updated",
    "agent_runtime.session.ended",
)
_REMOVED_PLANNING_TRIGGERS = (
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.dependency_resolved",
)


@dataclass(frozen=True)
class _Session:
    session_id: str
    closed_at: datetime | None = None
    lifecycle_status: str = "active"
    working_slug: str | None = None
    system_role: str | None = None
    project_path: str | None = None


class _FakeDb:
    def __init__(self, sessions: dict[str, _Session] | None = None) -> None:
        self._sessions = sessions or {}

    async def get_session(self, session_id: str) -> _Session | None:
        return self._sessions.get(session_id)

    async def list_sessions(self, *, include_closed: bool = False) -> list[_Session]:
        return [
            session
            for session in self._sessions.values()
            if include_closed or (session.closed_at is None and session.lifecycle_status != "closed")
        ]


class _RunnerClient:
    def __init__(self) -> None:
        self.requests: list[RunSessionArgs] = []
        self.messages: list[tuple[str, str, str]] = []
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def run_session(self, **kwargs: RunSessionArgs) -> CreateSessionResponseDTO:
        self.requests.append(kwargs)
        return CreateSessionResponseDTO(
            status="success",
            session_id=_SPAWN_SESSION,
            tmux_session_name="tmux-spawn-1",
        )

    async def send_message(self, session_id: str, computer: str, message: str) -> bool:
        self.messages.append((session_id, computer, message))
        return True


class _CapturingRegistry:
    """Task registry that captures spawned coroutines without running them.

    Submit paths spawn the operation runner via ``spawn``; closing the coroutine
    keeps the created-operation assertion deterministic (no background dispatch)
    and avoids "coroutine was never awaited" warnings.
    """

    def __init__(self) -> None:
        self.spawned = 0

    def spawn(self, coro: object, name: str | None = None) -> object:
        self.spawned += 1
        cast(Any, coro).close()
        return object()


class _WakePayload(TypedDict, total=False):
    project_path: str
    slug: str
    pickup_requested: bool


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


def _caller_identity(*, session_id: str = "caller", system_role: str | None = None) -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role=system_role,
        human_role="admin",
        tmux_session_name="tmux-caller",
        email="human@example.test",
    )


async def _add_todo(
    todos_db: TodosDb,
    slug: str,
    *,
    kind: str = _CHANGE,
    lifecycle_phase: str = LifecyclePhase.PREPARED.value,
    after: list[str] | None = None,
    active_runner: str | None = None,
    manually_started: bool = False,
    hold: bool = False,
    schedule: str | None = None,
) -> None:
    await todos_db.add_to_todo(slug, after=after, schedule=schedule)
    await todos_db.write_state(
        slug,
        TodoState(
            schema_version=5,
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            active_runner=active_runner,
            manually_started=manually_started,
            hold=hold,
        ).model_dump(exclude_none=True),
    )


async def _authorize_task_plan(todos_db: TodosDb, slug: str, body: str = "Do the task.") -> str:
    state = await todos_db.read_state(slug)
    assert state is not None
    await todos_db.write_artifact(slug, "task-plan", body)
    task_plan_digest = await todos_db.artifact_digest(slug, "task-plan")
    assert task_plan_digest
    state["artifacts"] = {"task_plan": {"digest": task_plan_digest}}
    state["approvals"] = {
        "task_approved": {
            "approved": True,
            "approved_digest": task_plan_digest,
            "approved_at": datetime.now(UTC).isoformat(),
        }
    }
    await todos_db.write_state(slug, state)
    return task_plan_digest


async def _add_kindless_todo(todos_db: TodosDb, slug: str) -> None:
    """Add a todo entry whose state carries no kind (kind-discovery pending).

    The stored state omits ``kind`` so the canonicalizer normalizes it to ``None``
    (a missing kind, not the ``TodoState`` default of ``feature``); this is the
    genuine kind-less shape the runner routes to kind discovery.
    """
    await todos_db.add_to_todo(slug, after=None)
    await todos_db.write_state(slug, {"schema_version": 4})


async def _group_into_child(todos_db: TodosDb, parent: str, child: str, *, kind: str = _CHANGE) -> None:
    """Build the holder shape: parent becomes a state-less holder, child owns state.

    Group-referencing the child purges the parent's state row, leaving the parent
    an active holder with no resolvable state while the child carries a runnable
    lifecycle state.
    """
    await todos_db.add_to_todo(child, group_slug=parent)
    await todos_db.write_state(
        child,
        TodoState(
            schema_version=5,
            kind=kind,
            lifecycle_phase=LifecyclePhase.DRAFT.value,
        ).model_dump(exclude_none=True),
    )


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_preparation_runs_regardless_of_autostart_only_work_is_gated() -> None:
    """Preparation always auto-dispatches: kind-discovery (analyze) and the
    prepare lane run even with every autostart kind off; only the work lane
    (prepared -> build) is gated by autostart."""
    decision = decide_dispatches(
        {
            "kindless-a": RunnerTodo(
                slug="kindless-a",
                status="active",
                kind=None,
                lifecycle_phase=None,
                hold=False,
                active_runner=None,
            ),
            "prepare-a": RunnerTodo(
                slug="prepare-a",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PRD_DRAFTING.value,
                hold=False,
                active_runner=None,
            ),
            "work-a": RunnerTodo(
                slug="work-a",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            ),
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: False, _CHANGE: False, "bug": False, _TASK: False},
        live_session_ids=set(),
    )

    lanes = {intent.slug: intent.lane for intent in decision.intents}
    assert lanes["kindless-a"] == RunnerLane.ANALYZE
    assert lanes["prepare-a"] == RunnerLane.PREPARE
    assert "work-a" not in lanes
    assert decision.skips[RunnerSkipReason.POLICY_DISABLED] == ["work-a"]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_blocked_dispatches_to_prepare_not_work() -> None:
    """BLOCKED is a prepare-lane phase: it must dispatch to PREPARE so the prepare
    machine can re-derive and clear the blockers — even with autostart off and a
    dependency that is prepared but not yet delivered. The prepare lane keys deps
    off prepared (met here), so it is neither policy-disabled (work-lane gate) nor
    dependency-blocked (work-lane delivered-dep gate)."""
    decision = decide_dispatches(
        {
            "blocked-a": RunnerTodo(
                slug="blocked-a",
                status="active",
                kind=_FEATURE,
                lifecycle_phase=LifecyclePhase.BLOCKED.value,
                hold=False,
                active_runner=None,
                after=("dep-a",),
            ),
        },
        prepared_slugs={"dep-a"},
        delivered_slugs=set(),
        autostart={_FEATURE: False, _CHANGE: False, "bug": False, _TASK: False},
        live_session_ids=set(),
    )

    lanes = {intent.slug: intent.lane for intent in decision.intents}
    assert lanes["blocked-a"] == RunnerLane.PREPARE
    skipped = [slug for slugs in decision.skips.values() for slug in slugs]
    assert "blocked-a" not in skipped


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_task_without_plan_dispatches_to_task_prepare() -> None:
    decision = decide_dispatches(
        {
            "task-a": RunnerTodo(
                slug="task-a",
                status="active",
                kind=_TASK,
                lifecycle_phase=LifecyclePhase.TASK_PLAN_DRAFTING.value,
                hold=False,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: False},
        live_session_ids=set(),
    )

    assert [(intent.slug, intent.lane, intent.command) for intent in decision.intents] == [
        ("task-a", RunnerLane.TASK_PREPARE, _NEXT_PREPARE_TASK)
    ]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_task_with_plan_requires_current_authorization() -> None:
    decision = decide_dispatches(
        {
            "missing-approval": RunnerTodo(
                slug="missing-approval",
                status="active",
                kind=_TASK,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
                task_plan_digest="plan-a",
            ),
            "stale-approval": RunnerTodo(
                slug="stale-approval",
                status="active",
                kind=_TASK,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
                task_plan_digest="plan-b",
                task_approved=True,
                task_approved_digest="old-plan",
            ),
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.TASK_AUTHORIZATION_MISSING] == ["missing-approval", "stale-approval"]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_authorized_task_dispatches_to_task_run_after_dependencies() -> None:
    blocked = RunnerTodo(
        slug="blocked",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        hold=False,
        active_runner=None,
        after=("dep-a",),
        task_plan_digest="plan-a",
        task_approved=True,
        task_approved_digest="plan-a",
    )
    ready = RunnerTodo(
        slug="ready",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        hold=False,
        active_runner=None,
        after=("dep-a",),
        task_plan_digest="plan-b",
        task_approved=True,
        task_approved_digest="plan-b",
    )

    before_dep = decide_dispatches(
        {"blocked": blocked},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: False},
        live_session_ids=set(),
    )
    after_dep = decide_dispatches(
        {"ready": ready},
        prepared_slugs=set(),
        delivered_slugs={"dep-a"},
        autostart={_TASK: True},
        live_session_ids=set(),
    )

    assert before_dep.intents == []
    assert before_dep.skips[RunnerSkipReason.DEPENDENCY_BLOCKED] == ["blocked"]
    assert [(intent.slug, intent.lane, intent.command) for intent in after_dep.intents] == [
        ("ready", RunnerLane.TASK_RUN, _NEXT_RUN_TASK)
    ]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_autonomous_task_run_honors_autostart_task() -> None:
    """The autonomous runner gates TASK_RUN on autostart.task, symmetric with the
    SDLC work lane. An authorized, due, no-dep task is POLICY_DISABLED when
    autostart.task is off and dispatches TASK_RUN when it is on."""
    ready = RunnerTodo(
        slug="ready",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        hold=False,
        active_runner=None,
        task_plan_digest="plan-a",
        task_approved=True,
        task_approved_digest="plan-a",
    )

    disabled = decide_dispatches(
        {"ready": ready},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: False},
        live_session_ids=set(),
    )
    enabled = decide_dispatches(
        {"ready": ready},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids=set(),
    )

    assert disabled.intents == []
    assert disabled.skips[RunnerSkipReason.POLICY_DISABLED] == ["ready"]
    assert [(intent.slug, intent.lane, intent.command) for intent in enabled.intents] == [
        ("ready", RunnerLane.TASK_RUN, _NEXT_RUN_TASK)
    ]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_stamped_terminal_state_suppresses_task_re_dispatch() -> None:
    """The outcome contract's correctness rests on the runner honoring the
    stamped terminal state: a delivered one-shot is DELIVERED, a held one-shot at
    task_running is HELD, and an un-held un-delivered authorized one-shot still
    dispatches TASK_RUN — the guard is the terminal state, not a blanket block."""
    delivered = RunnerTodo(
        slug="delivered-task",
        status="delivered",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.TASK_RUNNING.value,
        hold=False,
        active_runner=None,
        task_plan_digest="plan-a",
        task_approved=True,
        task_approved_digest="plan-a",
    )
    held = RunnerTodo(
        slug="held-task",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.TASK_RUNNING.value,
        hold=True,
        active_runner=None,
        task_plan_digest="plan-b",
        task_approved=True,
        task_approved_digest="plan-b",
    )
    runnable = RunnerTodo(
        slug="runnable-task",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        hold=False,
        active_runner=None,
        task_plan_digest="plan-c",
        task_approved=True,
        task_approved_digest="plan-c",
    )

    decision = decide_dispatches(
        {"delivered-task": delivered, "held-task": held, "runnable-task": runnable},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids=set(),
    )

    assert decision.skips[RunnerSkipReason.DELIVERED] == ["delivered-task"]
    assert decision.skips[RunnerSkipReason.HELD] == ["held-task"]
    assert [(intent.slug, intent.lane, intent.command) for intent in decision.intents] == [
        ("runnable-task", RunnerLane.TASK_RUN, _NEXT_RUN_TASK)
    ]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_authorized_task_with_future_schedule_is_not_dispatched() -> None:
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    decision = decide_dispatches(
        {
            "scheduled": RunnerTodo(
                slug="scheduled",
                status="active",
                kind=_TASK,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
                schedule=future,
                task_plan_digest="plan-a",
                task_approved=True,
                task_approved_digest="plan-a",
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: False},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.SCHEDULE_BLOCKED] == ["scheduled"]


@pytest.mark.spec(_SPEC, "UC-WSM4")
def test_authorized_recurring_task_dispatches_only_at_matching_cron_time() -> None:
    task = RunnerTodo(
        slug="weekly-task",
        status="active",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        hold=False,
        active_runner=None,
        schedule="cron:15 9 * * 0",
        task_plan_digest="plan-a",
        task_approved=True,
        task_approved_digest="plan-a",
    )

    matching = decide_dispatches(
        {"weekly-task": task},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids=set(),
        now=datetime(2026, 6, 21, 9, 15, tzinfo=UTC),
    )
    non_matching = decide_dispatches(
        {"weekly-task": task},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids=set(),
        now=datetime(2026, 6, 22, 9, 15, tzinfo=UTC),
    )

    assert [(intent.slug, intent.lane, intent.command) for intent in matching.intents] == [
        ("weekly-task", RunnerLane.TASK_RUN, _NEXT_RUN_TASK)
    ]
    assert non_matching.intents == []
    assert non_matching.skips[RunnerSkipReason.SCHEDULE_BLOCKED] == ["weekly-task"]


@pytest.mark.spec(_SPEC, "UC-WSM4")
async def test_due_recurring_task_with_live_runner_is_woken_not_redispatched(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        "task-a",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        active_runner=_LIVE_SESSION,
        schedule="cron:* * * * *",
    )
    await _authorize_task_plan(todos_db, "task-a", "Do the scheduled thing.")
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger=SCHEDULER_TICK_MINUTE,
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
        client_factory=lambda: client,
    )

    assert result.dispatched == []
    assert result.skips[RunnerSkipReason.ALREADY_DRIVEN] == ["task-a"]
    assert result.woken == ["task-a"]
    assert client.requests == []
    assert client.messages == [
        (
            _LIVE_SESSION,
            tc_config.computer.name,
            "Scheduled recurring firing is due for task `task-a`. Execute the next firing from the "
            "current task-plan, append the result to the log, and stay alive for follow-up.",
        )
    ]


@pytest.mark.spec(_SPEC, "UC-WSM4")
async def test_live_one_shot_task_is_not_rewoken_by_scheduler_tick(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    await _add_todo(
        todos_db,
        "task-a",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        active_runner=_LIVE_SESSION,
        schedule=past,
    )
    await _authorize_task_plan(todos_db, "task-a", "Do the one-shot thing.")
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger=SCHEDULER_TICK_MINUTE,
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
        client_factory=lambda: client,
    )

    assert result.dispatched == []
    assert result.woken == []
    assert client.messages == []


@pytest.mark.spec(_SPEC, "UC-WFL-27")
def test_manual_runner_mode_freezes_all_autonomous_dispatch() -> None:
    """Under manual mode the runner dispatches nothing on any lane —
    kind-discovery, prepare, and work are all frozen — even for a todo set
    that is eligible across every lane. The same set dispatches under
    autostart, proving the gate (not a regression) is what suppresses it."""
    eligible = {
        "kindless-a": RunnerTodo(
            slug="kindless-a",
            status="active",
            kind=None,
            lifecycle_phase=None,
            hold=False,
            active_runner=None,
        ),
        "prepare-a": RunnerTodo(
            slug="prepare-a",
            status="active",
            kind=_CHANGE,
            lifecycle_phase=LifecyclePhase.PRD_DRAFTING.value,
            hold=False,
            active_runner=None,
        ),
        "work-a": RunnerTodo(
            slug="work-a",
            status="active",
            kind=_CHANGE,
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            hold=False,
            active_runner=None,
        ),
    }
    full_autostart = {_FEATURE: True, _CHANGE: True, "bug": True, _TASK: True}

    manual = decide_dispatches(
        eligible,
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart=full_autostart,
        live_session_ids=set(),
        runner_mode=WorkflowRunnerMode.MANUAL,
    )
    assert manual.intents == []
    assert manual.evaluated == len(eligible)

    autostart = decide_dispatches(
        eligible,
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart=full_autostart,
        live_session_ids=set(),
        runner_mode=WorkflowRunnerMode.AUTOSTART,
    )
    assert {intent.slug for intent in autostart.intents} == set(eligible)


@pytest.mark.spec(_SPEC, "UC-WFL-23")
def test_hold_skips_prepare_lane_even_when_autostart_disabled() -> None:
    decision = decide_dispatches(
        {
            "draft-held": RunnerTodo(
                slug="draft-held",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value,
                hold=True,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_CHANGE: False},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.HELD] == ["draft-held"]


@pytest.mark.spec(_SPEC, "UC-WFL-23")
def test_work_lane_hold_skips_runner_as_held() -> None:
    """Hold stops autonomous dispatch in the work lane."""
    decision = decide_dispatches(
        {
            "work-held": RunnerTodo(
                slug="work-held",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.BUILD_STARTED.value,
                hold=True,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_CHANGE: True},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.HELD] == ["work-held"]


@pytest.mark.spec(_SPEC, "UC-WFL-23")
def test_prepared_hold_skips_under_active_autostart() -> None:
    """A held prepared todo is not auto-started into work."""
    decision = decide_dispatches(
        {
            "prepared-held": RunnerTodo(
                slug="prepared-held",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=True,
                active_runner=None,
            )
        },
        prepared_slugs={"prepared-held"},
        delivered_slugs=set(),
        autostart={_CHANGE: True},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.HELD] == ["prepared-held"]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_manual_runner_mode_short_circuits_before_hold_skip() -> None:
    """Manual runner mode freezes autonomous dispatch before per-todo gates."""
    decision = decide_dispatches(
        {
            "work-held": RunnerTodo(
                slug="work-held",
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.BUILD_STARTED.value,
                hold=True,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_CHANGE: True},
        live_session_ids=set(),
        runner_mode=WorkflowRunnerMode.MANUAL,
    )

    assert decision.intents == []
    assert RunnerSkipReason.HELD not in decision.skips


@pytest.mark.spec(_SPEC, "UC-WFL-23")
def test_kindless_hold_skips_analyze_dispatch() -> None:
    """A held kind-less todo does not enter autonomous kind discovery."""
    decision = decide_dispatches(
        {
            "kindless-held": RunnerTodo(
                slug="kindless-held",
                status="active",
                kind=None,
                lifecycle_phase=None,
                hold=True,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_CHANGE: False},
        live_session_ids=set(),
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.HELD] == ["kindless-held"]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_decide_skips_at_capacity() -> None:
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
        max_dispatch=2,
        live_driver_count=2,
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.AT_CAPACITY] == [_WORK_SLUG]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_claim_held_across_spawn(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert [intent.slug for intent in result.dispatched] == [_WORK_SLUG]
    claims = await list_dispatch_claims(todos_db)
    assert [(claim.slug, claim.lane) for claim in claims] == [(_WORK_SLUG, RunnerLane.WORK.value)]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_load_todos_does_not_clear_active_runner_under_outstanding_claim(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_SPAWN_SESSION)
    await runner_mod.acquire_dispatch_claim(todos_db, slug=_WORK_SLUG, lane=RunnerLane.WORK.value, owner="test-owner")

    # _SPAWN_SESSION is not live in _FakeDb; without the guard it would be cleared.
    loaded, reconciled = await runner_mod._load_todos(todos_db, cast(Db, _FakeDb()), claimed_slugs={_WORK_SLUG})

    assert reconciled == []
    assert loaded[_WORK_SLUG].active_runner == _SPAWN_SESSION
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_concurrent_passes_dispatch_once(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_kindless_todo(todos_db, _WORK_SLUG)

    gate = asyncio.Event()
    run_count = 0

    class _BlockingClient:
        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def run_session(self, **kwargs: RunSessionArgs) -> CreateSessionResponseDTO:
            nonlocal run_count
            run_count += 1
            await gate.wait()
            return CreateSessionResponseDTO(
                status="success",
                session_id=_SPAWN_SESSION,
                tmux_session_name="tmux-spawn-1",
            )

    async def _pass() -> object:
        return await run_lifecycle_runner(
            project_root,
            trigger="test",
            db=cast(Db, _FakeDb()),
            client_factory=lambda: _BlockingClient(),
        )

    task = asyncio.gather(_pass(), _pass())
    await asyncio.sleep(0)
    gate.set()
    await task

    assert run_count == 1


@pytest.mark.spec(_SPEC, "UC-WFL-25")
async def test_split_holder_is_never_dispatched_child_prepare_preserved(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, kind=_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value)
    await _group_into_child(todos_db, _PARENT, _CHILD)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert _PARENT not in {intent.slug for intent in result.dispatched}
    claims = await list_dispatch_claims(todos_db)
    assert all(claim.slug != _PARENT for claim in claims)
    assert (_CHILD, RunnerLane.PREPARE.value) in {(claim.slug, claim.lane) for claim in claims}
    assert any(request["command"] == _NEXT_PREPARE and request["args"] == _CHILD for request in client.requests)

    # Second pass with the first pass's claims still in place: the holder must
    # remain undispatched across passes, not merely on the first.
    second = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )
    assert _PARENT not in {intent.slug for intent in second.dispatched}


@pytest.mark.spec(_SPEC, "UC-WFL-26")
async def test_non_holder_stateless_row_still_dispatches_to_analyze(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    # A todo row with no state row and no child group-referencing it: the
    # genuine kind-discovery case the holder guard must not swallow.
    await todos_db.add_to_todo(_WORK_SLUG, after=None)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert _WORK_SLUG in {intent.slug for intent in result.dispatched}
    claims = await list_dispatch_claims(todos_db)
    assert (_WORK_SLUG, RunnerLane.ANALYZE.value) in {(claim.slug, claim.lane) for claim in claims}


def _operation(
    *,
    slug: str = _WORK_SLUG,
    caller_session_id: str = "caller-session",
    cwd: str | Path = "/unused",
) -> Operation:
    return Operation(
        operation_id="op-1",
        kind="todo_work",
        caller_session_id=caller_session_id,
        cwd=str(cwd),
        slug=slug,
        payload_json="{}",
        state="running",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_run_session_infers_working_slug_without_downgrading_orchestrator_role(tmp_path: Path) -> None:
    request = RunSessionRequest(
        command="/next-prepare",
        args=_WORK_SLUG,
        project=str(tmp_path / "project"),
        agent="claude",
    )

    plan = _prepare_run_session(request, _caller_identity())

    assert plan.working_slug == _WORK_SLUG
    assert plan.system_role == ROLE_ORCHESTRATOR


def test_integrator_may_dispatch_worker_review(tmp_path: Path) -> None:
    request = RunSessionRequest(
        command="/next-review-commits",
        args="7670dcbd9",
        project=str(tmp_path / "project"),
        agent="claude",
    )

    plan = _prepare_run_session(request, _caller_identity(system_role=ROLE_INTEGRATOR))

    assert plan.system_role == ROLE_WORKER


@pytest.mark.spec(_SPEC, "UC-WSM4")
@pytest.mark.parametrize(
    ("command", "expected_job"),
    [
        ("/next-prepare-task", "task-preparer"),
        ("/next-run-task", "task-runner"),
    ],
)
def test_task_commands_are_worker_slug_bound(command: str, expected_job: str, tmp_path: Path) -> None:
    request = RunSessionRequest(
        command=command,
        args=_WORK_SLUG,
        project=str(tmp_path / "project"),
        agent="claude",
    )

    plan = _prepare_run_session(request, _caller_identity())

    assert plan.system_role == ROLE_WORKER
    assert plan.working_slug == _WORK_SLUG
    assert plan.job == expected_job


@pytest.mark.spec(_SPEC, "UC-WSM4")
def test_task_commands_require_slug(tmp_path: Path) -> None:
    request = RunSessionRequest(
        command="/next-run-task",
        args="",
        project=str(tmp_path / "project"),
        agent="claude",
    )

    with pytest.raises(HTTPException) as exc:
        _prepare_run_session(request, _caller_identity())

    assert exc.value.status_code == 400


def test_integrator_may_not_dispatch_orchestrator(tmp_path: Path) -> None:
    request = RunSessionRequest(
        command="/next-prepare",
        args=_WORK_SLUG,
        project=str(tmp_path / "project"),
        agent="claude",
    )

    with pytest.raises(HTTPException) as exc:
        _prepare_run_session(request, _caller_identity(system_role=ROLE_INTEGRATOR))

    assert exc.value.status_code == 403


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_decision_pass_uses_dependency_first_order_for_full_project_set() -> None:
    decision = decide_dispatches(
        {
            _CHILD: RunnerTodo(
                slug=_CHILD,
                status="active",
                kind=_FEATURE,
                lifecycle_phase=LifecyclePhase.PRD_DRAFTING.value,
                hold=False,
                active_runner=None,
                after=(_PARENT,),
            ),
            _PARENT: RunnerTodo(
                slug=_PARENT,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            ),
        },
        prepared_slugs={_PARENT},
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
    )

    assert decision.evaluated == 2
    assert [(intent.slug, intent.lane) for intent in decision.intents] == [
        (_PARENT, RunnerLane.WORK),
        (_CHILD, RunnerLane.PREPARE),
    ]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_clears_stale_active_runner_before_dispatching(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_STALE_SESSION)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.reconciled == [_WORK_SLUG]
    assert [intent.slug for intent in result.dispatched] == [_WORK_SLUG]
    assert client.requests[0]["command"] == _NEXT_WORK
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state.get("manually_started") is False


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_start_dispatches_dedicated_runner_and_marks_manual_owner(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()

    result = await manual_start_lifecycle_session(
        project_root,
        _WORK_SLUG,
        lane=RunnerLane.WORK,
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.status is ManualLifecycleStatus.DISPATCHED
    assert result.session_id == _SPAWN_SESSION
    assert client.requests[0]["command"] == _NEXT_WORK
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-23")
async def test_manual_start_releases_held_todo_after_claim_check(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, hold=True)
    client = _RunnerClient()

    result = await manual_start_lifecycle_session(
        project_root,
        _WORK_SLUG,
        lane=RunnerLane.WORK,
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.status is ManualLifecycleStatus.DISPATCHED
    assert result.reason is None
    assert client.requests[0]["command"] == _NEXT_WORK
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["hold"] is False


@pytest.mark.spec(_SPEC, "UC-WFL-23")
async def test_manual_start_refuses_live_claimant(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION, hold=True)
    client = _RunnerClient()

    result = await manual_start_lifecycle_session(
        project_root,
        _WORK_SLUG,
        lane=RunnerLane.WORK,
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
        client_factory=lambda: client,
    )

    assert result.status is ManualLifecycleStatus.ALREADY_DRIVEN
    assert result.session_id == _LIVE_SESSION
    assert client.requests == []
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["hold"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_dispatch_intent_routes_unplanned_task_to_task_prepare(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "task-a", kind=_TASK, lifecycle_phase=LifecyclePhase.TASK_PLAN_DRAFTING.value)

    intent, reason = await resolve_manual_dispatch_intent(todos_db, "task-a")

    assert reason is None
    assert intent is not None
    assert (intent.slug, intent.lane, intent.command) == ("task-a", RunnerLane.TASK_PREPARE, _NEXT_PREPARE_TASK)


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_dispatch_intent_routes_authorized_task_to_task_run(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "task-a", kind=_TASK, lifecycle_phase=LifecyclePhase.PREPARED.value)
    await _authorize_task_plan(todos_db, "task-a")

    intent, reason = await resolve_manual_dispatch_intent(todos_db, "task-a")

    assert reason is None
    assert intent is not None
    assert (intent.slug, intent.lane, intent.command) == ("task-a", RunnerLane.TASK_RUN, _NEXT_RUN_TASK)


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_adoption_claims_unclaimed_slug_for_caller_bound_to_other_slug(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    # The operator session is bound to a different slug; it still claims the unclaimed todo in-process.
    caller = _Session(session_id="caller-session", working_slug=_OTHER_SLUG)

    result = await adopt_manual_lifecycle_session(
        project_root,
        _WORK_SLUG,
        caller.session_id,
        db=cast(Db, _FakeDb({caller.session_id: caller})),
    )

    assert result.status is ManualLifecycleStatus.ADOPTED
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == caller.session_id
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_adoption_marks_authorized_task_as_task_run(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "task-a", kind=_TASK, lifecycle_phase=LifecyclePhase.PREPARED.value)
    await _authorize_task_plan(todos_db, "task-a")
    caller = _Session(session_id="caller-session", working_slug="task-a")

    result = await adopt_manual_lifecycle_session(
        project_root,
        "task-a",
        caller.session_id,
        db=cast(Db, _FakeDb({caller.session_id: caller})),
    )

    assert result.status is ManualLifecycleStatus.ADOPTED
    assert result.lane is RunnerLane.TASK_RUN
    state = await todos_db.read_state("task-a")
    assert state is not None
    assert state["active_runner"] == caller.session_id
    assert state["manually_started"] is True
    assert state["lifecycle_phase"] == LifecyclePhase.TASK_RUNNING.value


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_adopts_bound_caller_and_continues_in_place(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    caller = _Session(session_id="caller-session", working_slug=_WORK_SLUG)
    service = OperationsService(
        db=cast(Db, _FakeDb({caller.session_id: caller})),
        task_registry=cast(TaskRegistry, object()),
    )
    operation = _operation(caller_session_id=caller.session_id)
    operation.cwd = str(project_root)

    async def _continue_in_place(op: Operation) -> str:
        assert op is operation
        return _CONTINUED

    result = await service._run_todo_lifecycle_operation(
        operation,
        lane=RunnerLane.WORK,
        state_machine=_continue_in_place,
    )

    assert result == _CONTINUED
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == caller.session_id
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_unbound_caller_dispatches_dedicated_runner(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=cast(TaskRegistry, object()),
        lifecycle_client_factory=lambda: client,
    )
    operation = _operation()
    operation.cwd = str(project_root)

    async def _unexpected_continue(_op: Operation) -> str:
        raise AssertionError("unbound callers must not run the state machine in place")

    result = await service._run_todo_lifecycle_operation(
        operation,
        lane=RunnerLane.WORK,
        state_machine=_unexpected_continue,
    )

    assert result == f"RUNNER_DISPATCHED: {_WORK_SLUG} work {_SPAWN_SESSION}"
    assert client.requests[0]["command"] == _NEXT_WORK


@pytest.mark.spec(_SPEC, "UC-WFL-20")
@pytest.mark.spec(_PREPARE_SPEC, "UC-WPS11")
async def test_operation_bridge_caller_bound_to_other_slug_claims_in_place_without_dispatch(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    # A live operator session bound to a different slug invokes on the unclaimed todo.
    caller = _Session(session_id="caller-session", working_slug=_OTHER_SLUG)
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb({caller.session_id: caller})),
        task_registry=cast(TaskRegistry, object()),
        lifecycle_client_factory=lambda: client,
    )
    operation = _operation(caller_session_id=caller.session_id)
    operation.cwd = str(project_root)

    async def _continue_in_place(op: Operation) -> str:
        assert op is operation
        return _CONTINUED

    result = await service._run_todo_lifecycle_operation(
        operation,
        lane=RunnerLane.WORK,
        state_machine=_continue_in_place,
    )

    assert result == _CONTINUED
    assert client.requests == []
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == caller.session_id
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_suppresses_live_active_runner_and_does_not_prefix_match(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _LIVE_SLUG, active_runner=_LIVE_SESSION)
    await _add_todo(todos_db, _OTHER_SLUG)
    client = _RunnerClient()
    live_session = _Session(session_id=_LIVE_SESSION)

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb({_LIVE_SESSION: live_session})),
        client_factory=lambda: client,
    )

    assert result.skips[RunnerSkipReason.ALREADY_DRIVEN] == [_LIVE_SLUG]
    assert [intent.slug for intent in result.dispatched] == [_OTHER_SLUG]
    assert client.requests[0]["args"] == _OTHER_SLUG


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_live_orchestrator_owner_resolves_only_same_project_orchestrator(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    other_root = (tmp_path / "other").resolve()
    sessions = {
        _ORCH_SESSION: _Session(
            session_id=_ORCH_SESSION,
            working_slug=_WORK_SLUG,
            system_role=ROLE_ORCHESTRATOR,
            project_path=str(project_root),
        ),
        "closed-orch": _Session(
            session_id="closed-orch",
            closed_at=datetime(2026, 1, 1),
            working_slug=_WORK_SLUG,
            system_role=ROLE_ORCHESTRATOR,
            project_path=str(project_root),
        ),
        "worker-session": _Session(
            session_id="worker-session",
            working_slug=_WORK_SLUG,
            system_role=None,
            project_path=str(project_root),
        ),
        _CROSS_PROJECT_SESSION: _Session(
            session_id=_CROSS_PROJECT_SESSION,
            working_slug=_WORK_SLUG,
            system_role=ROLE_ORCHESTRATOR,
            project_path=str(other_root),
        ),
    }
    db = cast(Db, _FakeDb(sessions))

    assert await live_orchestrator_owner(db, project_root, _WORK_SLUG) == _ORCH_SESSION
    assert await live_orchestrator_owner(db, project_root, _OTHER_SLUG) is None
    assert await live_orchestrator_owner(db, other_root, _WORK_SLUG) == _CROSS_PROJECT_SESSION
    assert await live_orchestrator_owned_slugs(db, project_root) == {_WORK_SLUG}
    assert await live_orchestrator_owned_slugs(db, other_root) == {_WORK_SLUG}


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_decide_skips_registry_owned_slug_without_active_runner() -> None:
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_CHANGE: True},
        live_session_ids=set(),
        orchestrator_owned_slugs={_WORK_SLUG},
    )

    assert decision.skips[RunnerSkipReason.ALREADY_DRIVEN] == [_WORK_SLUG]
    assert decision.intents == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_decide_dedups_task_driver_via_active_runner_without_registry() -> None:
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_TASK,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=_LIVE_SESSION,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_TASK: True},
        live_session_ids={_LIVE_SESSION},
        orchestrator_owned_slugs=set(),
    )

    assert decision.skips[RunnerSkipReason.ALREADY_DRIVEN] == [_WORK_SLUG]
    assert decision.intents == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_skips_registry_owned_slug_without_active_runner(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    client = _RunnerClient()
    orchestrator = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb({_ORCH_SESSION: orchestrator})),
        client_factory=lambda: client,
    )

    assert result.skips[RunnerSkipReason.ALREADY_DRIVEN] == [_WORK_SLUG]
    assert result.dispatched == []
    assert client.requests == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_does_not_block_same_slug_in_other_project(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    other_root = (tmp_path / "other").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    client = _RunnerClient()
    orchestrator = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(other_root),
    )

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb({_ORCH_SESSION: orchestrator})),
        client_factory=lambda: client,
    )

    assert [intent.slug for intent in result.dispatched] == [_WORK_SLUG]
    assert RunnerSkipReason.ALREADY_DRIVEN not in result.skips


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_start_refused_by_registry_owner_without_active_runner(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    client = _RunnerClient()
    orchestrator = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    result = await manual_start_lifecycle_session(
        project_root,
        _WORK_SLUG,
        lane=RunnerLane.WORK,
        db=cast(Db, _FakeDb({_ORCH_SESSION: orchestrator})),
        client_factory=lambda: client,
    )

    assert result.status is ManualLifecycleStatus.ALREADY_DRIVEN
    assert result.session_id == _ORCH_SESSION
    assert client.requests == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_adoption_not_self_blocked_by_own_registry_row(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    caller = _Session(
        session_id="caller-session",
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    result = await adopt_manual_lifecycle_session(
        project_root,
        _WORK_SLUG,
        caller.session_id,
        db=cast(Db, _FakeDb({caller.session_id: caller})),
    )

    assert result.status is ManualLifecycleStatus.ADOPTED
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == caller.session_id


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_adoption_refusal_reports_registry_owner_without_active_runner(tmp_path: Path) -> None:
    project_root = (tmp_path / "project").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    owner = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    result = await adopt_manual_lifecycle_session(
        project_root,
        _WORK_SLUG,
        "caller-session",
        db=cast(Db, _FakeDb({_ORCH_SESSION: owner})),
    )

    assert result.status is ManualLifecycleStatus.ALREADY_DRIVEN
    assert result.session_id == _ORCH_SESSION


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_guard_driver_start_refuses_orchestrator_self_create(tmp_path: Path) -> None:
    """An orchestrator-class create is refused against a live holder even when the
    requesting session IS the holder — a second orchestrator row is never created."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION)

    with pytest.raises(ClaimConflict) as exc:
        await guard_driver_start(
            project_root,
            _WORK_SLUG,
            launch_class=DriverLaunchClass.ORCHESTRATOR,
            caller_session_id=_LIVE_SESSION,
            db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
        )

    assert exc.value.holder == _LIVE_SESSION
    assert _LIVE_SESSION in exc.value.summary()


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_guard_driver_start_refuses_orchestrator_against_registry_owner(tmp_path: Path) -> None:
    """An orchestrator-class create is refused against a live registry orchestrator
    owner from a different session, even without a live active_runner."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    owner = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    with pytest.raises(ClaimConflict) as exc:
        await guard_driver_start(
            project_root,
            _WORK_SLUG,
            launch_class=DriverLaunchClass.ORCHESTRATOR,
            caller_session_id="caller-session",
            db=cast(Db, _FakeDb({_ORCH_SESSION: owner})),
        )

    assert exc.value.holder == _ORCH_SESSION


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_guard_driver_start_refuses_duplicate_task_runner(tmp_path: Path) -> None:
    """A task-lane create self-exempts the dispatching orchestrator on the registry
    path but is still refused by a live active_runner for the slug."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION)
    orchestrator = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(project_root),
    )

    with pytest.raises(ClaimConflict) as exc:
        await guard_driver_start(
            project_root,
            _WORK_SLUG,
            launch_class=DriverLaunchClass.TASK_LANE,
            caller_session_id=_ORCH_SESSION,
            db=cast(
                Db,
                _FakeDb({_ORCH_SESSION: orchestrator, _LIVE_SESSION: _Session(session_id=_LIVE_SESSION)}),
            ),
        )

    assert exc.value.holder == _LIVE_SESSION


@pytest.mark.spec(_VERSIONING_SPEC, "UC-WAV13")
async def test_write_acquired_claim_blocks_subsequent_dispatch(tmp_path: Path) -> None:
    """A claim acquired by writing a prepare artifact is honored by driver-start:
    the atomic write binds active_runner, which guard_driver_start then refuses."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    writer = "write-claim-session"

    async def _no_live_holder(_active_runner: str | None) -> str | None:
        return None

    refused = await todos_db.write_prepare_artifact_with_claim(
        _WORK_SLUG,
        ARTIFACT_PRD,
        "# PRD",
        updated_by=writer,
        claimant_session_id=writer,
        resolve_live_holder=_no_live_holder,
    )
    assert refused is None
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == writer

    with pytest.raises(ClaimConflict) as exc:
        await guard_driver_start(
            project_root,
            _WORK_SLUG,
            launch_class=DriverLaunchClass.ORCHESTRATOR,
            caller_session_id="other-session",
            db=cast(Db, _FakeDb({writer: _Session(session_id=writer)})),
        )

    assert exc.value.holder == writer


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_guard_driver_start_allows_worker_child_spawn(tmp_path: Path) -> None:
    """A non-driver worker child-spawn shares working_slug with its orchestrator and
    is never deduped, even against a live holder."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION)

    await guard_driver_start(
        project_root,
        _WORK_SLUG,
        launch_class=DriverLaunchClass.WORKER_CHILD,
        caller_session_id="caller-session",
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
    )


@pytest.mark.spec("project/spec/feature/agent_runtime/run-session-with-command", "Lifecycle driver-start dedup")
async def test_guard_driver_start_allows_first_spawn_without_holder(tmp_path: Path) -> None:
    """An orchestrator-class create is allowed when no live driver holds the slug —
    the autonomous runner's sanctioned first spawn."""
    project_root = (tmp_path / "project").resolve()
    await _project_db(project_root)
    todos_db = await get_todos_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None, hold=True)

    await guard_driver_start(
        project_root,
        _WORK_SLUG,
        launch_class=DriverLaunchClass.ORCHESTRATOR,
        caller_session_id="caller-session",
        db=cast(Db, _FakeDb()),
    )
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["hold"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-23")
async def test_operation_bridge_refuses_live_driver_from_other_session(tmp_path: Path) -> None:
    """The operator op door fails the operation with a ClaimConflict carrying the
    holder when a live driver from another session already holds the slug."""
    project_root = (tmp_path / "project").resolve()
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION, hold=True)
    service = OperationsService(
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(session_id=_LIVE_SESSION)})),
        task_registry=cast(TaskRegistry, object()),
    )
    operation = _operation(caller_session_id="caller-session")
    operation.cwd = str(project_root)

    async def _never_continues(_op: Operation) -> str:
        raise AssertionError("state machine must not run on a driver-start conflict")

    with pytest.raises(ClaimConflict) as exc:
        await service._run_todo_lifecycle_operation(
            operation,
            lane=RunnerLane.WORK,
            state_machine=_never_continues,
        )

    assert exc.value.holder == _LIVE_SESSION
    assert _LIVE_SESSION in exc.value.summary()
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _LIVE_SESSION
    assert state["hold"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_dispatches_task_prepare_regardless_of_task_autostart(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "task-a", kind=_TASK, lifecycle_phase=LifecyclePhase.TASK_PLAN_DRAFTING.value)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert [(intent.slug, intent.lane) for intent in result.dispatched] == [("task-a", RunnerLane.TASK_PREPARE)]
    assert client.requests[0]["command"] == _NEXT_PREPARE_TASK


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_hold_blocks_task_prepare(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        "task-a",
        kind=_TASK,
        lifecycle_phase=LifecyclePhase.TASK_PLAN_DRAFTING.value,
        hold=True,
    )
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.dispatched == []
    assert result.skips[RunnerSkipReason.HELD] == ["task-a"]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_decision_treats_closed_active_runner_as_not_driven() -> None:
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=_STALE_SESSION,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
    )

    assert [intent.slug for intent in decision.intents] == [_WORK_SLUG]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_pending_approval_gate_parks_runner_independently_of_hold() -> None:
    todo = RunnerTodo(
        slug=_FEATURE,
        status="active",
        kind=_FEATURE,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        hold=True,
        active_runner=None,
    )

    assert pending_approval_gate({"kind": todo.kind, "lifecycle_phase": todo.lifecycle_phase}) is ApprovalGate.PRD

    decision = decide_dispatches(
        {_FEATURE: todo},
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
    )

    assert decision.intents == []
    # Approval-pending is checked before hold; both would skip this todo, but the
    # checks are independent — neither suppresses the other.
    assert decision.skips[RunnerSkipReason.APPROVAL_PENDING] == [_FEATURE]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_approval_gate_and_hold_are_independent() -> None:
    # Changing hold never changes the approval result.
    base = {"kind": _CHANGE, "lifecycle_phase": LifecyclePhase.PRD_HUMAN_APPROVAL.value}
    assert pending_approval_gate({**base, "hold": False}) is ApprovalGate.PRD
    assert pending_approval_gate({**base, "hold": True}) is ApprovalGate.PRD

    # effective_hold reads only the stored hold flag; approval, phase, kind, and
    # autostart never change the hold verdict.
    assert effective_hold(hold=True) is True
    assert effective_hold(hold=False) is False


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_pending_approval_gate_returns_none_for_running_or_work_ready_todos() -> None:
    assert pending_approval_gate({"kind": _CHANGE, "lifecycle_phase": LifecyclePhase.PREPARED.value}) is None
    assert pending_approval_gate({"kind": _CHANGE, "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value}) is None


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_lifecycle_router_delegates_named_wakeups_to_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_root = str(tmp_path / "project")
    calls: list[tuple[str, str]] = []

    async def _capture_runner(project_path: str, *, trigger: str, client_factory: object) -> object:
        _ = client_factory
        calls.append((project_path, trigger))
        return object()

    monkeypatch.setattr(lifecycle_router, "run_lifecycle_runner", _capture_runner)

    for event_name in _WAKE_EVENTS:
        payload = _WakePayload(project_path=project_root)
        if event_name == "workflow.todo.created":
            payload["slug"] = _WORK_SLUG
            payload["pickup_requested"] = True
        event = EventEnvelope(
            event=event_name,
            source=_SOURCE,
            level=EventLevel.WORKFLOW,
            domain=_DOMAIN,
            payload=payload,
        )
        await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    assert calls == [(project_root, event_name) for event_name in _WAKE_EVENTS]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_lifecycle_router_skips_wakeup_when_project_identity_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _capture_runner(project_path: str, *, trigger: str, client_factory: object) -> object:
        _ = client_factory
        calls.append((project_path, trigger))
        return object()

    monkeypatch.setattr(lifecycle_router, "run_lifecycle_runner", _capture_runner)

    for event_name in _WAKE_EVENTS:
        payload: _WakePayload = {}
        if event_name == "workflow.todo.created":
            payload["slug"] = _WORK_SLUG
            payload["pickup_requested"] = True
        event = EventEnvelope(
            event=event_name,
            source=_SOURCE,
            level=EventLevel.WORKFLOW,
            domain=_DOMAIN,
            payload=payload,
        )
        await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    assert calls == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_lifecycle_router_passes_through_removed_planning_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _capture_runner(project_path: str, *, trigger: str, client_factory: object) -> object:
        _ = (project_path, client_factory)
        calls.append(trigger)
        return object()

    monkeypatch.setattr(lifecycle_router, "run_lifecycle_runner", _capture_runner)

    for event_name in _REMOVED_PLANNING_TRIGGERS:
        assert event_name not in lifecycle_router._TRIGGER_EVENTS
        event = EventEnvelope(
            event=event_name,
            source=_SOURCE,
            level=EventLevel.WORKFLOW,
            domain=_DOMAIN,
            payload=_WakePayload(project_path="/tmp/project"),
        )
        result = await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))
        assert result is event

    assert calls == []


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_removed_planning_events_are_not_registered() -> None:
    catalog = EventCatalog()
    register_all(catalog)

    for event_name in _REMOVED_PLANNING_TRIGGERS:
        assert catalog.get(event_name) is None
    assert catalog.get(SCHEDULER_TICK_MINUTE) is not None
    assert catalog.get("domain.software-development.planning.todo_finalize_ready") is not None


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-22")
async def test_manual_session_close_sets_hold_on_active_runner_todo(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_CLOSE_HOLD_SESSION)
    runtime_db = await db_mod.get_db()
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="tmux-close-hold-session",
        last_input_origin="terminal",
        title="runner",
        project_path=str(project_root),
        session_id=_CLOSE_HOLD_SESSION,
        human_role="member",
        emit_session_started=False,
    )

    result = await hold_todo_for_manual_session_close(runtime_db, _CLOSE_HOLD_SESSION)

    assert result.mutated is True
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["hold"] is True
    hold_audit = state["hold_audit"]
    assert isinstance(hold_audit, dict)
    assert hold_audit["source"] == _HOLD_SOURCE_SESSION_CLOSE


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-23")
async def test_manual_session_close_sets_hold_on_autostart_disabled_kind(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    session_id = f"{tmp_path.name}-autostart-off-close"
    await _add_todo(todos_db, _WORK_SLUG, active_runner=session_id)
    runtime_db = await db_mod.get_db()
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="tmux-close-autostart-off",
        last_input_origin="terminal",
        title="runner",
        project_path=str(project_root),
        session_id=session_id,
        human_role="member",
        emit_session_started=False,
    )

    result = await hold_todo_for_manual_session_close(runtime_db, session_id)

    assert result.mutated is True
    assert result.reason == session_hold.MANUAL_CLOSE_HELD_REASON
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["hold"] is True
    hold_audit = state["hold_audit"]
    assert isinstance(hold_audit, dict)
    assert hold_audit["source"] == _HOLD_SOURCE_SESSION_CLOSE


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-22")
async def test_session_end_clears_active_runner_link(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_CLOSE_END_SESSION)
    runtime_db = await db_mod.get_db()
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="tmux-ended-session",
        last_input_origin="terminal",
        title="runner",
        project_path=str(project_root),
        session_id=_CLOSE_END_SESSION,
        human_role="member",
        emit_session_started=False,
    )

    result = await clear_active_runner_for_session_end(runtime_db, _CLOSE_END_SESSION)

    assert result.mutated is True
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert "active_runner" not in state


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-22")
async def test_session_end_emits_session_ended_wakeup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session_id = "session-ended-wakeup"
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=session_id)
    runtime_db = await db_mod.get_db()
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="tmux-ended-wakeup",
        last_input_origin="terminal",
        title="runner",
        project_path=str(project_root),
        session_id=session_id,
        human_role="member",
        emit_session_started=False,
    )

    ended: list[tuple[object, object]] = []

    async def _capture_emit(event: str, source: str, level: object, **kwargs: object) -> str:
        _ = (source, level)
        payload = kwargs.get("payload")
        if event == "agent_runtime.session.ended" and isinstance(payload, dict):
            ended.append((payload.get("session_id"), payload.get("project_path")))
        return "captured"

    monkeypatch.setattr(session_hold, "emit_event", _capture_emit)

    await clear_active_runner_for_session_end(runtime_db, session_id)

    assert ended == [(session_id, str(project_root.resolve()))]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_delivery_fires_delivered_hook_with_commit(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)

    delivered: list[tuple[str, str | None, str]] = []
    todos_db._on_delivered = lambda slug, commit, delivered_at: delivered.append((slug, commit, delivered_at))

    ok = await todos_db.deliver(_WORK_SLUG, commit=_DELIVERY_COMMIT)

    assert ok is True
    assert len(delivered) == 1
    seen_slug, seen_commit, seen_delivered_at = delivered[0]
    assert seen_slug == _WORK_SLUG
    assert seen_commit == _DELIVERY_COMMIT
    assert seen_delivered_at


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_sync_delivery_fires_delivered_hook_with_commit(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)

    delivered: list[tuple[str, str | None, str]] = []
    todos_db._on_delivered = lambda slug, commit, delivered_at: delivered.append((slug, commit, delivered_at))

    ok = todos_db.deliver_sync(_WORK_SLUG, commit=_SYNC_DELIVERY_COMMIT)

    assert ok is True
    assert len(delivered) == 1
    seen_slug, seen_commit, _ = delivered[0]
    assert seen_slug == _WORK_SLUG
    assert seen_commit == _SYNC_DELIVERY_COMMIT


def _work_intent(slug: str) -> DispatchIntent:
    return DispatchIntent(
        slug=slug,
        lane=RunnerLane.WORK,
        command=_NEXT_WORK,
        thinking_mode="med",
        additional_context="",
    )


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_primitive_runner_origin_writes_active_runner_not_manual(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    client = _RunnerClient()

    session_id = await dispatch_lifecycle_session(
        client=client,
        todos_db=todos_db,
        project_path=str(project_root),
        intent=_work_intent(_WORK_SLUG),
        origin=DispatchOrigin.RUNNER,
    )

    assert session_id == _SPAWN_SESSION
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state["manually_started"] is False


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_primitive_manual_origin_marks_manually_started(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)
    client = _RunnerClient()

    session_id = await dispatch_lifecycle_session(
        client=client,
        todos_db=todos_db,
        project_path=str(project_root),
        intent=_work_intent(_WORK_SLUG),
        origin=DispatchOrigin.MANUAL,
    )

    assert session_id == _SPAWN_SESSION
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_dispatches_natural_prepare_lane_for_draft_operator_start(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value,
        active_runner=None,
    )
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.WORK,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == f"RUNNER_DISPATCHED: {_WORK_SLUG} prepare {_SPAWN_SESSION}"
    assert client.requests[0]["command"] == _NEXT_PREPARE
    assert client.requests[0]["args"] == _WORK_SLUG
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state["manually_started"] is True


@pytest.mark.spec(_SPEC, "UC-WFL-24")
async def test_operation_bridge_honors_explicit_prepare_lane_on_prepared_todo(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        active_runner=None,
    )
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.PREPARE,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == snapshot
    assert client.requests[0]["command"] == _NEXT_PREPARE


@pytest.mark.spec(_SPEC, "UC-WFL-24")
async def test_operation_bridge_explicit_prepare_does_not_force_kindless(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_kindless_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.PREPARE,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == snapshot
    assert client.requests == []


@pytest.mark.spec(_SPEC, "UC-WFL-24")
async def test_operation_bridge_work_lane_on_prepared_todo_stays_work(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        lifecycle_phase=LifecyclePhase.PREPARED.value,
        active_runner=None,
    )
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.WORK,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == snapshot
    assert client.requests[0]["command"] == _NEXT_WORK


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_submit_work_records_task_run_kind_for_task_and_todo_work_for_sdlc(tmp_path: Path) -> None:
    """The single /todos/work submit self-resolves the operation kind from the
    todo's kind: a kind=task start persists a `task_run` operation while an SDLC
    kind persists `todo_work`."""
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "sdlc-a", kind=_CHANGE, lifecycle_phase=LifecyclePhase.PREPARED.value)
    await _add_todo(todos_db, "task-a", kind=_TASK, lifecycle_phase=LifecyclePhase.PREPARED.value)
    await _authorize_task_plan(todos_db, "task-a")
    db = Db(":memory:")
    await db.initialize()
    service = OperationsService(db=db, task_registry=cast(TaskRegistry, _CapturingRegistry()))

    sdlc_op = await service.submit_todo_work(
        slug="sdlc-a", cwd=str(project_root), caller_session_id="caller", client_request_id=None
    )
    task_op = await service.submit_todo_work(
        slug="task-a", cwd=str(project_root), caller_session_id="caller", client_request_id=None
    )

    assert sdlc_op["kind"] == OPERATION_KIND_TODO_WORK
    assert task_op["kind"] == OPERATION_KIND_TASK_RUN


@pytest.mark.spec(_SPEC, "UC-WFL-23")
async def test_operation_bridge_releases_held_todo_as_manual_forward_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, hold=True)
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.WORK,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == f"RUNNER_DISPATCHED: {_WORK_SLUG} work {_SPAWN_SESSION}"
    assert client.requests[0]["command"] == _NEXT_WORK
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION
    assert state["hold"] is False


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_claims_approval_pending_todo(tmp_path: Path) -> None:
    # Claim-only manual start: an unclaimed todo parked at a pending human-approval
    # phase is dispatched by the op door, not refused by the phase. The phase
    # gate belongs to the autonomous runner alone
    # (see test_pending_approval_gate_parks_runner_independently_of_hold).
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        kind=_FEATURE,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
    )
    client = _RunnerClient()
    service = OperationsService(
        db=cast(Db, _FakeDb()),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: client,
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.WORK,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == f"RUNNER_DISPATCHED: {_WORK_SLUG} prepare {_SPAWN_SESSION}"
    assert client.requests[0]["command"] == _NEXT_PREPARE
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _SPAWN_SESSION


@pytest.mark.spec(_SPEC, "UC-WFL-23")
async def test_manual_adoption_releases_held_approval_pending_slug(tmp_path: Path) -> None:
    # The claim-only contract holds at the door, at a pending human-approval phase:
    # the manual door claims the held but unclaimed slug in-process and clears the
    # hold. The phase never refuses the start. Guards a re-introduction of the
    # leaked gate at the shared chokepoint's nearest public surface.
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        kind=_FEATURE,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        hold=True,
    )
    caller = _Session(session_id="caller-session")

    result = await adopt_manual_lifecycle_session(
        project_root,
        _WORK_SLUG,
        caller.session_id,
        db=cast(Db, _FakeDb({caller.session_id: caller})),
    )

    assert result.status is ManualLifecycleStatus.ADOPTED
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == caller.session_id
    assert state["manually_started"] is True
    assert state["hold"] is False


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_cap_excludes_manual_drivers_from_count() -> None:
    # Cap == 2 with two MANUAL drivers already live: the runner still has full
    # budget because manual drivers are not counted.
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
        max_dispatch=2,
        live_driver_count=0,
    )

    assert [intent.slug for intent in decision.intents] == [_WORK_SLUG]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
def test_cap_counts_auto_drivers_and_skips_at_capacity() -> None:
    # Cap == 2 with two AUTO drivers live: the new eligible candidate is skipped.
    decision = decide_dispatches(
        {
            _WORK_SLUG: RunnerTodo(
                slug=_WORK_SLUG,
                status="active",
                kind=_CHANGE,
                lifecycle_phase=LifecyclePhase.PREPARED.value,
                hold=False,
                active_runner=None,
            )
        },
        prepared_slugs=set(),
        delivered_slugs=set(),
        autostart={_FEATURE: True, _CHANGE: True, "bug": True, _TASK: False},
        live_session_ids=set(),
        max_dispatch=2,
        live_driver_count=2,
    )

    assert decision.intents == []
    assert decision.skips[RunnerSkipReason.AT_CAPACITY] == [_WORK_SLUG]


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_pass_excludes_manual_driver_from_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # One manual driver live + a fresh candidate; cap == 1. The manual driver is
    # not counted, so the fresh candidate still auto-dispatches.
    monkeypatch.setattr(tc_config.workflow, "max_todo_dispatch", 1)

    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _LIVE_SLUG, active_runner=_LIVE_SESSION, manually_started=True)
    await _add_todo(todos_db, _OTHER_SLUG)
    client = _RunnerClient()
    live_session = _Session(session_id=_LIVE_SESSION)

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb({_LIVE_SESSION: live_session})),
        client_factory=lambda: client,
    )

    assert result.skips.get(RunnerSkipReason.ALREADY_DRIVEN) == [_LIVE_SLUG]
    assert [intent.slug for intent in result.dispatched] == [_OTHER_SLUG]
    assert RunnerSkipReason.AT_CAPACITY not in result.skips


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_adoption_writes_active_runner_and_manual_marker(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=None)

    # Before adoption: the headless session holds no claim on the todo.
    pre = await todos_db.read_state(_WORK_SLUG)
    assert pre is not None
    assert "active_runner" not in pre

    adopted = await adopt_headless_session(todos_db=todos_db, slug=_WORK_SLUG, session_id=_LIVE_SESSION)

    assert adopted is True
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert state["active_runner"] == _LIVE_SESSION
    assert state["manually_started"] is True


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-22")
async def test_session_end_clears_manually_started(tmp_path: Path) -> None:
    manual_end_session = "close-end-manual-session"
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=manual_end_session, manually_started=True)
    runtime_db = await db_mod.get_db()
    await runtime_db.create_session(
        computer_name="local",
        tmux_session_name="tmux-ended-manual-session",
        last_input_origin="terminal",
        title="runner",
        project_path=str(project_root),
        session_id=manual_end_session,
        human_role="member",
        emit_session_started=False,
    )

    result = await clear_active_runner_for_session_end(runtime_db, manual_end_session)

    assert result.mutated is True
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert "active_runner" not in state
    assert state.get("manually_started") in (False, None)


@pytest.mark.spec(_STAMPING_SPEC, "UC-WSS10")
async def test_notify_runner_of_gate_approval_messages_linked_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator approval (TUI flag) messages the parked runner session linked to the slug."""
    project_root = tmp_path
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _WORK_SLUG,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        kind="feature",
        active_runner=_LIVE_SESSION,
    )
    calls: list[tuple[str, str]] = []

    async def _fake_notify(session_id: str, *, slug: str) -> bool:
        calls.append((session_id, slug))
        return True

    async def _fake_get_todos_db(_root: object) -> TodosDb:
        return todos_db

    monkeypatch.setattr(session_hold, "notify_gate_approved", _fake_notify)
    monkeypatch.setattr(session_hold, "get_todos_db", _fake_get_todos_db)
    monkeypatch.setattr(session_hold, "resolve_state_root", lambda cwd: Path(cwd))

    result = await notify_runner_of_gate_approval(str(project_root), _WORK_SLUG)

    assert result is True
    assert calls == [(_LIVE_SESSION, _WORK_SLUG)]


@pytest.mark.spec(_STAMPING_SPEC, "UC-WSS10")
async def test_notify_runner_of_gate_approval_noop_without_active_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No live runner is linked (agent already exited) -> nothing is messaged."""
    project_root = tmp_path
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        _OTHER_SLUG,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        kind="feature",
        active_runner=None,
    )
    calls: list[tuple[str, str]] = []

    async def _fake_notify(session_id: str, *, slug: str) -> bool:
        calls.append((session_id, slug))
        return True

    async def _fake_get_todos_db(_root: object) -> TodosDb:
        return todos_db

    monkeypatch.setattr(session_hold, "notify_gate_approved", _fake_notify)
    monkeypatch.setattr(session_hold, "get_todos_db", _fake_get_todos_db)
    monkeypatch.setattr(session_hold, "resolve_state_root", lambda cwd: Path(cwd))

    result = await notify_runner_of_gate_approval(str(project_root), _OTHER_SLUG)

    assert result is False
    assert calls == []


class _RecordingCommandService:
    """Captures ProcessMessageCommand deliveries; optionally fails to exercise best-effort."""

    def __init__(self, *, fail: bool = False) -> None:
        self.commands: list[ProcessMessageCommand] = []
        self._fail = fail

    async def process_message(self, cmd: ProcessMessageCommand) -> None:
        if self._fail:
            raise SessionMessageRejectedError(session_id=cmd.session_id, reason="closed")
        self.commands.append(cmd)


@pytest.mark.spec(_STAMPING_SPEC, "UC-WSS10")
async def test_notify_gate_approved_injects_into_open_session(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    """The real injection path delivers a [TeleClaude Notification] into a live, open session."""
    svc = _RecordingCommandService()

    async def _get_session(_sid: str) -> _Session:
        return _Session(session_id=_LIVE_SESSION, lifecycle_status="active")

    monkeypatch.setattr(session_listeners_mod.db, "get_session", _get_session)
    monkeypatch.setattr(session_listeners_mod, "get_command_service", lambda: svc)

    result = await session_listeners_mod.notify_gate_approved(_LIVE_SESSION, slug=_WORK_SLUG)

    assert result is True
    assert len(svc.commands) == 1
    cmd = svc.commands[0]
    assert cmd.session_id == _LIVE_SESSION
    assert cmd.origin == InputOrigin.TERMINAL.value
    assert cmd.actor_name == session_listeners_mod.NOTIFY_ACTOR_NAME
    assert cmd.text == snapshot


@pytest.mark.spec(_STAMPING_SPEC, "UC-WSS10")
async def test_notify_gate_approved_skips_closed_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed/closing target session is never messaged."""
    svc = _RecordingCommandService()

    async def _get_session(_sid: str) -> _Session:
        return _Session(session_id=_LIVE_SESSION, lifecycle_status="closed")

    monkeypatch.setattr(session_listeners_mod.db, "get_session", _get_session)
    monkeypatch.setattr(session_listeners_mod, "get_command_service", lambda: svc)

    result = await session_listeners_mod.notify_gate_approved(_LIVE_SESSION, slug=_WORK_SLUG)

    assert result is False
    assert svc.commands == []


@pytest.mark.spec(_STAMPING_SPEC, "UC-WSS10")
async def test_notify_gate_approved_is_best_effort_on_delivery_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivery failure after the approval stamp returns False, never raising into the caller."""
    svc = _RecordingCommandService(fail=True)

    async def _get_session(_sid: str) -> _Session:
        return _Session(session_id=_LIVE_SESSION, lifecycle_status="active")

    monkeypatch.setattr(session_listeners_mod.db, "get_session", _get_session)
    monkeypatch.setattr(session_listeners_mod, "get_command_service", lambda: svc)

    result = await session_listeners_mod.notify_gate_approved(_LIVE_SESSION, slug=_WORK_SLUG)

    assert result is False


def _init_main_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real main checkout plus a linked git worktree under trees/.

    Returns ``(main_root, worktree_path)`` where ``worktree_path`` is an
    *unrelated* feature worktree — the shape that wakes the runner with a
    non-canonical ``project_path``. Real git metadata is used so
    ``resolve_state_root`` exercises the gitdir-walk rather than a mocked
    normalizer.
    """
    main_root = (tmp_path / "main").resolve()
    main_root.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(main_root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Runner Test")
    repo.git.config("user.email", "runner-test@example.test")
    (main_root / "README.md").write_text("initial\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    worktree_path = main_root / WORKTREE_DIR / _OTHER_WORKTREE_SLUG
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    repo.git.worktree("add", "-b", _OTHER_WORKTREE_SLUG, str(worktree_path), "HEAD")
    return main_root, worktree_path.resolve()


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_runner_pickup_in_worktree_dispatches_orchestrator_on_main(tmp_path: Path) -> None:
    """An event whose project_path is an unrelated feature worktree dispatches the
    orchestrator with the canonical main checkout as its cwd and no subfolder."""
    main_root, worktree_path = _init_main_with_worktree(tmp_path)
    todos_db = await _project_db(main_root)
    await _add_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        worktree_path,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert [intent.slug for intent in result.dispatched] == [_WORK_SLUG]
    request = client.requests[0]
    assert Path(request["project_path"]).resolve() == main_root
    assert "subfolder" not in request


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_start_in_worktree_dispatches_orchestrator_on_main(tmp_path: Path) -> None:
    """An operator START invoked from inside a feature worktree dispatches the
    orchestrator with the canonical main checkout as its cwd and no subfolder."""
    main_root, worktree_path = _init_main_with_worktree(tmp_path)
    todos_db = await _project_db(main_root)
    await _add_todo(todos_db, _WORK_SLUG)
    client = _RunnerClient()

    result = await manual_start_lifecycle_session(
        worktree_path,
        _WORK_SLUG,
        lane=RunnerLane.WORK,
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.status is ManualLifecycleStatus.DISPATCHED
    request = client.requests[0]
    assert Path(request["project_path"]).resolve() == main_root
    assert "subfolder" not in request


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_adoption_in_worktree_matches_main_root_live_owner(tmp_path: Path) -> None:
    """Adoption invoked from a feature worktree normalizes to the main checkout
    before the project-scoped live-owner check, so a main-root orchestrator owner
    is seen and the worktree caller is refused as ALREADY_DRIVEN."""
    main_root, worktree_path = _init_main_with_worktree(tmp_path)
    todos_db = await _project_db(main_root)
    await _add_todo(todos_db, _WORK_SLUG)
    owner = _Session(
        session_id=_ORCH_SESSION,
        working_slug=_WORK_SLUG,
        system_role=ROLE_ORCHESTRATOR,
        project_path=str(main_root),
    )

    result = await adopt_manual_lifecycle_session(
        worktree_path,
        _WORK_SLUG,
        "different-caller",
        db=cast(Db, _FakeDb({owner.session_id: owner})),
    )

    assert result.status is ManualLifecycleStatus.ALREADY_DRIVEN
    assert result.session_id == _ORCH_SESSION
