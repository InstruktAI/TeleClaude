"""Functional tests bound to the workflow todo-creation spec."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import Unpack, cast

import pytest

from teleclaude.cli.api_client import RunSessionArgs
from teleclaude.cli.telec import main
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
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
_PARENT = "parent"
_CHILD = "child"
_NEXT_PREPARE = "/next-prepare"


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
) -> None:
    await todos_db.add_to_roadmap(slug, after=after)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": _KIND_CHANGE,
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


def _created_event(payload: Mapping[str, str | bool]) -> EventEnvelope:
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

    async def run_session(self, **kwargs: Unpack[RunSessionArgs]) -> None:
        self.calls.append(kwargs)

    async def close(self) -> None:
        return None


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
async def test_lifecycle_router_consumes_dep_blocked_create_without_dispatch(
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

    assert not _CapturingTelecAPIClient.calls


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

    [call] = _CapturingTelecAPIClient.calls
    assert call["command"] == _NEXT_PREPARE
    assert call["args"] == _CHILD
    assert call["project_path"] == str(event_project)
