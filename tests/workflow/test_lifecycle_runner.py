"""Functional tests for the state-derived lifecycle runner."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

import pytest

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.sessions_actions_routes import _prepare_run_session
from teleclaude.api_models import CreateSessionResponseDTO, RunSessionRequest
from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.config import config as tc_config
from teleclaude.constants import ROLE_ORCHESTRATOR, format_system_message
from teleclaude.core import db as db_mod
from teleclaude.core import session_listeners as session_listeners_mod
from teleclaude.core.conversation_messages import TeleClaudeNotificationLabel
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine import lifecycle_runner as runner_mod
from teleclaude.core.next_machine import session_hold
from teleclaude.core.next_machine.dispatch_claims import list_dispatch_claims
from teleclaude.core.next_machine.lifecycle import ApprovalGate, HumanControl, hold_state, pending_approval_gate
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
    manual_start_lifecycle_session,
    run_lifecycle_runner,
)
from teleclaude.core.next_machine.session_hold import (
    clear_active_runner_for_session_end,
    hold_todo_for_manual_session_close,
    notify_runner_of_gate_approval,
)
from teleclaude.core.operations.service import OperationsService
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.events.cartridges import lifecycle_router
from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.schemas import register_all
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/domain/workflow"
_FEATURE = "feature"
_CHANGE = "change"
_TASK = "task"
_PARENT = "parent"
_CHILD = "child"
_WORK_SLUG = "work-a"
_LIVE_SLUG = "live-a"
_OTHER_SLUG = "other-a"
_STALE_SESSION = "stale-session"
_LIVE_SESSION = "live-session"
_SPAWN_SESSION = "spawn-1"
_CLOSE_HOLD_SESSION = "close-hold-session"
_CLOSE_END_SESSION = "close-end-session"
_NEXT_WORK = "/next-work"
_NEXT_PREPARE = "/next-prepare"
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


class _FakeDb:
    def __init__(self, sessions: dict[str, _Session] | None = None) -> None:
        self._sessions = sessions or {}

    async def get_session(self, session_id: str) -> _Session | None:
        return self._sessions.get(session_id)


class _RunnerClient:
    def __init__(self) -> None:
        self.requests: list[RunSessionArgs] = []
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
) -> None:
    await todos_db.add_to_roadmap(slug, after=after)
    await todos_db.write_state(
        slug,
        TodoState(
            schema_version=4,
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            active_runner=active_runner,
            manually_started=manually_started,
            hold=hold,
        ).model_dump(exclude_none=True),
    )


async def _add_kindless_todo(todos_db: TodosDb, slug: str) -> None:
    """Add a roadmap entry whose state carries no kind (kind-discovery pending)."""
    await todos_db.add_to_roadmap(slug, after=None)
    await todos_db.write_state(
        slug,
        TodoState(schema_version=4).model_dump(exclude_none=True),
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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_start_refuses_live_claimant(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION)
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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_manual_adoption_requires_matching_working_slug(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG)
    caller = _Session(session_id="caller-session", working_slug=_WORK_SLUG)

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
async def test_runner_skips_task_as_policy_disabled_not_hold(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "task-a", kind=_TASK)
    client = _RunnerClient()

    result = await run_lifecycle_runner(
        project_root,
        trigger="test",
        db=cast(Db, _FakeDb()),
        client_factory=lambda: client,
    )

    assert result.dispatched == []
    assert result.skips[RunnerSkipReason.POLICY_DISABLED] == ["task-a"]
    assert RunnerSkipReason.HELD not in result.skips


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
def test_approval_gate_and_hold_state_are_independent() -> None:
    # Changing hold never changes the approval result.
    base = {"kind": _CHANGE, "lifecycle_phase": LifecyclePhase.PRD_HUMAN_APPROVAL.value}
    assert pending_approval_gate({**base, "hold": False}) is ApprovalGate.PRD
    assert pending_approval_gate({**base, "hold": True}) is ApprovalGate.PRD

    # Changing the approval phase never changes the hold result.
    assert hold_state({"hold": True, "lifecycle_phase": LifecyclePhase.PRD_HUMAN_APPROVAL.value}) is HumanControl.HOLD
    assert hold_state({"hold": True, "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value}) is HumanControl.HOLD
    assert hold_state({"hold": False, "lifecycle_phase": LifecyclePhase.PRD_HUMAN_APPROVAL.value}) is None


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
    assert catalog.get("domain.software-development.planning.todo_finalize_ready") is not None


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-22")
async def test_manual_session_close_sets_hold_on_active_runner_todo(tmp_path: Path) -> None:
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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_reports_already_driven_for_repeated_operator_start(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _WORK_SLUG, active_runner=_LIVE_SESSION, manually_started=True)
    service = OperationsService(
        db=cast(Db, _FakeDb({_LIVE_SESSION: _Session(_LIVE_SESSION)})),
        task_registry=TaskRegistry(),
        lifecycle_client_factory=lambda: _RunnerClient(),
    )

    result = await service._run_todo_lifecycle_operation(
        _operation(slug=_WORK_SLUG, cwd=project_root),
        lane=RunnerLane.WORK,
        state_machine=lambda _operation: asyncio.sleep(0, result="SHOULD_NOT_RUN"),
    )

    assert result == f"ALREADY_DRIVEN: {_WORK_SLUG} is already driven by active runner {_LIVE_SESSION}"


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_does_not_dispatch_held_todo(tmp_path: Path) -> None:
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

    assert result == f"RUNNER_NOT_DISPATCHED: {_WORK_SLUG} held"
    assert client.requests == []
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert "active_runner" not in state


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_operation_bridge_does_not_dispatch_approval_pending_todo(tmp_path: Path) -> None:
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

    assert result == f"RUNNER_NOT_DISPATCHED: {_WORK_SLUG} approval-pending"
    assert client.requests == []
    state = await todos_db.read_state(_WORK_SLUG)
    assert state is not None
    assert "active_runner" not in state


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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
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
            raise RuntimeError("delivery boom")
        self.commands.append(cmd)


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_notify_gate_approved_injects_into_open_session(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert format_system_message(TeleClaudeNotificationLabel.NOTIFICATION) in cmd.text
    assert _WORK_SLUG in cmd.text


@pytest.mark.spec(_SPEC, "UC-WFL-20")
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


@pytest.mark.spec(_SPEC, "UC-WFL-20")
async def test_notify_gate_approved_is_best_effort_on_delivery_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivery failure after the approval stamp returns False, never raising into the caller."""
    svc = _RecordingCommandService(fail=True)

    async def _get_session(_sid: str) -> _Session:
        return _Session(session_id=_LIVE_SESSION, lifecycle_status="active")

    monkeypatch.setattr(session_listeners_mod.db, "get_session", _get_session)
    monkeypatch.setattr(session_listeners_mod, "get_command_service", lambda: svc)

    result = await session_listeners_mod.notify_gate_approved(_LIVE_SESSION, slug=_WORK_SLUG)

    assert result is False
