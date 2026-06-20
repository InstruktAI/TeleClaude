"""Functional tests bound to the workflow todo-split spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from teleclaude.api import todo_routes
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.constants import ARTIFACT_IMPLEMENTATION_PLAN, ARTIFACT_INPUT
from teleclaude.core.todos_db import HolderWriteRefused, TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_CHANGE, TODO_KIND_FEATURE, TODO_KIND_TASK

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-split"
_PARENT = "parent-slug"
_CHILD_A = "child-a"
_CHILD_B = "child-b"
_INPUT_BODY = "# parent-slug - Input\n\nSplit this work.\n"


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
    kind: str | None,
    lifecycle_phase: LifecyclePhase | None,
) -> None:
    await todos_db.add_to_todo(slug)
    state: dict[str, StateValue] = {
        "schema_version": 4,
        "kind": kind,
        "phase": "pending",
    }
    if lifecycle_phase is not None:
        state["lifecycle_phase"] = lifecycle_phase.value
    await todos_db.write_state(slug, state)


@pytest.mark.spec(_SPEC, "UC-WTS1")
async def test_split_change_parent_children_inherit_change_and_clone_input(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, kind=TODO_KIND_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, _INPUT_BODY, updated_by="test")

    await todo_routes.todo_split(slug=_PARENT, children=[_CHILD_A, _CHILD_B], cwd=str(project_root))

    entries = await todos_db.list_todo()
    children_by_slug = {entry["slug"]: entry for entry in entries if entry["slug"] in {_CHILD_A, _CHILD_B}}
    assert children_by_slug[_CHILD_A]["group_slug"] == _PARENT
    assert children_by_slug[_CHILD_B]["group_slug"] == _PARENT
    for child in (_CHILD_A, _CHILD_B):
        state = await todos_db.read_state(child)
        assert state is not None
        assert state["kind"] == TODO_KIND_CHANGE
        assert state["lifecycle_phase"] == LifecyclePhase.DRAFT.value
        assert await todos_db.read_artifact(child, ARTIFACT_INPUT) == _INPUT_BODY
    assert await todos_db.read_state(_PARENT) is None


@pytest.mark.spec(_SPEC, "UC-WTS2")
async def test_split_children_follow_parent_kind_entry_phase_for_supported_kinds(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    parent_cases = {
        "feature-parent": (TODO_KIND_FEATURE, LifecyclePhase.PRD_DRAFTING, LifecyclePhase.DRAFT),
        "bug-parent": (TODO_KIND_BUG, LifecyclePhase.DIAGNOSE, LifecyclePhase.DIAGNOSE),
        "task-parent": (TODO_KIND_TASK, LifecyclePhase.PREPARED, LifecyclePhase.PREPARED),
    }

    for parent, (kind, parent_phase, expected_child_phase) in parent_cases.items():
        child = f"{parent}-child"
        await _add_todo(todos_db, parent, kind=kind, lifecycle_phase=parent_phase)

        await todo_routes.todo_split(slug=parent, children=[child], cwd=str(project_root))

        state = await todos_db.read_state(child)
        assert state is not None
        assert state["kind"] == kind
        assert state["lifecycle_phase"] == expected_child_phase.value


@pytest.mark.spec(_SPEC, "UC-WTS3")
async def test_split_refuses_unresolvable_parent_kind_before_child_writes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, kind=None, lifecycle_phase=None)

    with pytest.raises(HTTPException) as exc:
        await todo_routes.todo_split(slug=_PARENT, children=[_CHILD_A], cwd=str(project_root))

    assert exc.value.status_code == 409
    assert not await todos_db.slug_in_todo(_CHILD_A)
    parent_state = await todos_db.read_state(_PARENT)
    assert parent_state is not None
    assert parent_state["kind"] is None
    assert "lifecycle_phase" not in parent_state


@pytest.mark.spec(_SPEC, "UC-WTS4")
async def test_split_emits_no_workflow_todo_created_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    emitted: list[object] = []

    async def _capture_emit_event(**kwargs: object) -> None:
        emitted.append(kwargs)

    monkeypatch.setattr(todo_routes, "emit_event", _capture_emit_event)
    await _add_todo(todos_db, _PARENT, kind=TODO_KIND_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)

    await todo_routes.todo_split(slug=_PARENT, children=[_CHILD_A], cwd=str(project_root))

    assert not emitted


@pytest.mark.spec(_SPEC, "UC-WTS5")
def test_split_success_output_instructs_agent_to_tend_children(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_split([_PARENT, "--into", _CHILD_A, "--into", _CHILD_B])

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _PARENT
    assert json_body["children"] == [_CHILD_A, _CHILD_B]
    assert Path(json_body["cwd"]) == project_root
    captured = capsys.readouterr()
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot


@pytest.mark.spec(_SPEC, "UC-WTS8")
async def test_holder_artifact_write_returns_clean_409_not_500(tmp_path: Path) -> None:
    """A write to a holder is refused with a clean 409 (and a typed db error), never a raw 500."""
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _PARENT, kind=TODO_KIND_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await todos_db.write_artifact(_PARENT, ARTIFACT_INPUT, _INPUT_BODY, updated_by="test")
    await todo_routes.todo_split(slug=_PARENT, children=[_CHILD_A, _CHILD_B], cwd=str(project_root))

    assert await todos_db.is_holder(_PARENT) is True

    # API surface: a holder write returns a clean 409, not a raw 500.
    with pytest.raises(HTTPException) as exc:
        await todo_routes.write_artifact(
            slug=_PARENT,
            name=ARTIFACT_IMPLEMENTATION_PLAN,
            content="# parent-slug — Implementation Plan\n",
            cwd=str(project_root),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail

    # DB surface: the refusal is the typed HolderWriteRefused (a ValueError subclass) —
    # this is what proves the 409 above is the holder path, not another conflict.
    with pytest.raises(HolderWriteRefused):
        await todos_db.write_artifact(_PARENT, ARTIFACT_IMPLEMENTATION_PLAN, "# plan\n", updated_by="test")
