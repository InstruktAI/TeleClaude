"""Functional tests bound to the workflow todo-creation spec."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import TypedDict, Unpack, cast

import pytest

from teleclaude.api import todo_routes
from teleclaude.api_models import CreateSessionResponseDTO, TodoDumpRequest
from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.cli.telec import main
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.roadmap import assemble_roadmap_from_db
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.events.cartridges import lifecycle_router
from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.pipeline import PipelineContext

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-creation"
_WORKFLOW_TODO_CREATED = "workflow.todo.created"
_SOURCE = "api.todo.create"
_DOMAIN = "software-development"
_KIND_CHANGE = "change"
_KIND_BUG = "bug"
_PARENT = "parent"
_CHILD = "child"
_KINDLESS = "kindless"
_NEXT_PREPARE = "/next-prepare"
_NEXT_WORK = "/next-work"
_ANALYZE_TODO_INPUT = "/analyze-todo-input"
_HOLD_SOURCE_CREATION = "creation"
_CAPTURED_SESSION = "captured-session"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _add_todo(
    todos_db: TodosDb,
    slug: str,
    *,
    lifecycle_phase: LifecyclePhase,
    after: list[str] | None = None,
    kind: str = _KIND_CHANGE,
) -> None:
    await todos_db.add_to_roadmap(slug, after=after)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": kind,
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


def _created_event(payload: Mapping[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event=_WORKFLOW_TODO_CREATED,
        source=_SOURCE,
        level=EventLevel.WORKFLOW,
        domain=_DOMAIN,
        payload=dict(payload),
    )


class _CapturingTelecAPIClient:
    calls: list[RunSessionArgs] = []

    async def connect(self) -> None:
        return None

    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> CreateSessionResponseDTO:
        self.calls.append(kwargs)
        return CreateSessionResponseDTO(
            status="success",
            session_id=_CAPTURED_SESSION,
            tmux_session_name="tmux-captured-session",
        )

    async def close(self) -> None:
        return None


class _EmittedEvent(TypedDict, total=False):
    payload: object


@pytest.mark.spec(_SPEC, "UC-WTC1")
def test_create_help_exposes_canonical_kind_choices(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    monkeypatch.setattr(sys, "argv", ["telec", "todo", "create", "--help"])

    main()

    captured = capsys.readouterr()
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot


@pytest.mark.spec(_SPEC, "UC-WTC2")
async def test_lifecycle_router_wake_up_evaluates_full_project_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    todos_db = await _project_db(event_project)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_CHANGE,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == _PARENT
    assert call["project_path"] == str(event_project)


@pytest.mark.spec(_SPEC, "UC-WTC3")
async def test_lifecycle_router_dispatches_deps_satisfied_create_from_event_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    event_db = await _project_db(event_project)
    await _add_todo(event_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(event_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    env_db = await get_todos_db(env_project)
    await _add_todo(env_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(env_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_CHANGE,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    assert [(call["command"], call["args"]) for call in _CapturingTelecAPIClient.calls] == [
        (_NEXT_WORK, _PARENT),
        (_NEXT_PREPARE, _CHILD),
    ]
    assert {call["project_path"] for call in _CapturingTelecAPIClient.calls} == {str(event_project)}


@pytest.mark.spec(_SPEC, "UC-WTC5")
async def test_kindless_create_persists_no_phase_and_dispatches_analyzer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    await todo_routes.todo_content_create(
        TodoDumpRequest(slug=_KINDLESS, content="Classify this raw dump.", cwd=str(project_root))
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state(_KINDLESS)
    assert state is not None
    assert state["kind"] is None
    assert "lifecycle_phase" not in state

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] is None
    assert payload["lifecycle_phase"] is None

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _ANALYZE_TODO_INPUT
    assert call["args"] == _KINDLESS
    assert call["project_path"] == str(project_root)


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-21")
async def test_create_with_hold_persists_visible_brake_and_suppresses_pickup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="held-change",
            content="Park this until released.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            hold=True,
        )
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state("held-change")
    assert state is not None
    assert state["hold"] is True
    hold_audit = state["hold_audit"]
    assert isinstance(hold_audit, dict)
    assert hold_audit["source"] == _HOLD_SOURCE_CREATION
    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["pickup_requested"] is False
    [todo] = assemble_roadmap_from_db(str(project_root))
    assert todo.hold is True
    assert todo.hold_source == _HOLD_SOURCE_CREATION


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-19")
async def test_legacy_silent_is_hold_for_non_task_but_not_for_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="silent-change",
            content="Legacy parked change.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            silent=True,
        )
    )
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="task-default",
            content="Task stays gated by policy.",
            kind="task",
            cwd=str(project_root),
            silent=True,
        )
    )

    todos_db = await get_todos_db(project_root)
    change_state = await todos_db.read_state("silent-change")
    task_state = await todos_db.read_state("task-default")
    assert change_state is not None
    assert task_state is not None
    assert change_state["hold"] is True
    assert task_state["hold"] is False
    pickup_requested: list[object] = []
    for event in emitted:
        payload = event["payload"]
        assert isinstance(payload, Mapping)
        pickup_requested.append(payload["pickup_requested"])
    assert pickup_requested == [False, False]


@pytest.mark.spec(_SPEC, "UC-WTC4")
async def test_lifecycle_router_dispatches_prepare_for_bug_in_diagnose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    event_db = await _project_db(event_project)
    await _add_todo(event_db, _CHILD, lifecycle_phase=LifecyclePhase.DIAGNOSE, kind=_KIND_BUG)
    await get_todos_db(env_project)
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []
    event = _created_event(
        {
            "slug": _CHILD,
            "kind": _KIND_BUG,
            "pickup_requested": True,
            "lifecycle_phase": LifecyclePhase.DIAGNOSE.value,
            "project_path": str(event_project),
        }
    )

    await LifecycleRouterCartridge().process(event, cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == _CHILD
