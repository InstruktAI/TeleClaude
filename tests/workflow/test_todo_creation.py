"""Functional tests bound to the workflow todo-creation spec."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import TypedDict, Unpack, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from teleclaude.api import todo_routes
from teleclaude.api_models import CreateSessionResponseDTO, TodoDumpRequest
from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.constants import ARTIFACT_IMPLEMENTATION_PLAN, ARTIFACT_INPUT, RoadmapStatus
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.state_mutation import StateWriter
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
_PARKED = "parked-idea"
_NEXT_PREPARE = "/next-prepare"
_NEXT_WORK = "/next-work"
_ANALYZE_TODO_INPUT = "/analyze-todo-input"
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


@pytest.mark.spec(_SPEC, "UC-WTC11")
async def test_icebox_create_parks_todo_and_suppresses_dispatch(
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
        TodoDumpRequest(
            slug=_PARKED,
            content="Park this idea until promoted.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            icebox=True,
        )
    )

    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state(_PARKED)
    assert state is not None
    assert await todos_db.read_artifact(_PARKED, ARTIFACT_INPUT)

    [todo] = assemble_roadmap_from_db(str(project_root), include_icebox=True, icebox_only=True)
    assert todo.slug == _PARKED
    assert todo.status == RoadmapStatus.ICEBOX
    assert todo.ready_since is None

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["pickup_requested"] is False

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))
    assert _CapturingTelecAPIClient.calls == []


@pytest.mark.spec(_SPEC, "UC-WTC12")
async def test_group_create_attaches_child_and_derives_parent_holder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)

    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, f"# {_PARENT} — Input\n\nParent scope.\n", updated_by="test")

    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=_CHILD,
            content="Grouped child created complete.",
            kind=_KIND_CHANGE,
            cwd=str(project_root),
            group=_PARENT,
        )
    )

    child_state = await todos_db.read_state(_CHILD)
    assert child_state is not None
    [child] = [t for t in assemble_roadmap_from_db(str(project_root), include_icebox=True) if t.slug == _CHILD]
    assert child.group == _PARENT

    assert await todos_db.is_holder(_PARENT) is True
    # Parent stripped to a structural holder: non-input state purged, frozen input retained.
    assert await todos_db.read_state(_PARENT) is None
    assert await todos_db.read_artifact(_PARENT, ARTIFACT_INPUT)

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["slug"] == _CHILD


@pytest.mark.spec(_SPEC, "UC-WTC13")
async def test_project_root_create_targets_explicit_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    invocation_cwd = tmp_path / "invocation"
    target_project = tmp_path / "other-project"
    invocation_cwd.mkdir()
    target_project.mkdir()

    # CLI handler maps --project-root to the request cwd, not the invocation cwd.
    tool_api_request = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: invocation_cwd)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_create(
        ["remote-task", "Targeted create.", "--kind", _KIND_CHANGE, "--project-root", str(target_project)]
    )

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert Path(json_body["cwd"]) == target_project

    # Route honors the supplied cwd: the todo and its event land in the targeted project.
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug="remote-task",
            content="Targeted create.",
            kind=_KIND_CHANGE,
            cwd=str(target_project),
        )
    )

    target_db = await get_todos_db(target_project)
    assert await target_db.read_state("remote-task") is not None
    invocation_db = await get_todos_db(invocation_cwd)
    assert await invocation_db.read_state("remote-task") is None
    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["project_path"] == str(target_project)


@pytest.mark.spec(_SPEC, "UC-WTC14")
@pytest.mark.parametrize("retired_field", ["hold", "release", "silent"])
def test_retired_create_parking_fields_are_rejected(retired_field: str) -> None:
    with pytest.raises(ValidationError):
        TodoDumpRequest.model_validate(
            {
                "slug": "rejected",
                "content": "Stale client body.",
                "kind": _KIND_CHANGE,
                retired_field: True,
            }
        )


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


async def test_create_with_plan_seeds_plan_drafting_and_dispatches_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: object,
) -> None:
    event_project = tmp_path / "event-project"
    env_project = tmp_path / "env-project"
    await _project_db(event_project)
    await get_todos_db(env_project)
    emitted: list[_EmittedEvent] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(cast(_EmittedEvent, kwargs))

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    monkeypatch.setenv("TELECLAUDE_PROJECT_PATH", str(env_project))
    monkeypatch.setattr(lifecycle_router, "TelecAPIClient", _CapturingTelecAPIClient)
    _CapturingTelecAPIClient.calls = []

    slug = "seeded-change"
    await todo_routes.todo_content_create(
        TodoDumpRequest(
            slug=slug,
            content="Step 1: do the thing.",
            kind=_KIND_CHANGE,
            cwd=str(event_project),
            plan=True,
        )
    )

    todos_db = await get_todos_db(event_project)
    # The supplied content lands as the implementation-plan artifact (not input),
    # written under the "# <slug> — Implementation Plan" header. Snapshot the
    # exact body so a dropped header or substituted/placeholder content fails.
    plan_body = await todos_db.read_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN)
    assert plan_body == snapshot
    state = await todos_db.read_state(slug)
    assert state is not None
    writer = StateWriter(state)
    assert writer.state.lifecycle_phase == LifecyclePhase.PLAN_DRAFTING.value
    assert writer.state.artifacts.implementation_plan.seeded is True
    # The seed is not auto-approved: plan-review stays unstamped (empty verdict).
    assert not writer.state.plan_review.verdict

    [event_kwargs] = emitted
    payload = event_kwargs["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == _KIND_CHANGE
    assert payload["lifecycle_phase"] == LifecyclePhase.PLAN_DRAFTING.value
    assert payload["pickup_requested"] is True
    payload["project_path"] = str(event_project)

    await LifecycleRouterCartridge().process(_created_event(payload), cast(PipelineContext, object()))

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == slug
    assert call["project_path"] == str(event_project)
