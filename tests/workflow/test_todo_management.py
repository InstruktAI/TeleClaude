"""Functional tests for todo management CLI request scoping."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TypeGuard
from unittest.mock import MagicMock

import pytest

from teleclaude.cli.telec.handlers import _todo_show
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.todo import assemble_todo_from_db
from teleclaude.core.todos_db import close_todos_db_instances, get_todos_db
from teleclaude.core.todos_db._show import ShowPayload, TodoShowPayload, assemble_show_payload

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-management"
_STATELESS_ANCHOR = "stateless-anchor"
_DEPENDENT_CHILD = "dependent-child"
_STRUCTURAL_HOLDER = "structural-holder"
_STRUCTURAL_CHILD = "structural-child"
_HOLDER_INPUT = "# Holder input"
_SLUG_KEY = "slug"
_STAGE_KEY = "stage"
_HOLDER_STAGE = "holder"
_TODO_KEY = "roadmap"
_INPUT_ARTIFACT = "input"
_ARTIFACTS_KEY = "artifacts"
_ARTIFACT_CONTENT_KEY = "artifact_content"
_CURRENT_KEY = "current"
_STATE_KEY = "state"
_CHILDREN_KEY = "children"
_HOLD_SOURCE_MANUAL = "manual"
_ACTIVE_RUNNER = "session-123"
_HOLDER_STRUCTURAL_KEYS = frozenset(
    {
        _SLUG_KEY,
        _STAGE_KEY,
        _TODO_KEY,
        _ARTIFACTS_KEY,
        _ARTIFACT_CONTENT_KEY,
    }
)
_TODO_LIFECYCLE_PAYLOAD_KEYS = frozenset(
    {
        _CURRENT_KEY,
        _STATE_KEY,
        "approvals",
        "reviews",
        "drift",
        "work",
        "audit",
        "events",
        "next_commands",
        "previous",
        "next",
        "blocked_by",
    }
)


def _is_todo_show_payload(payload: ShowPayload) -> TypeGuard[TodoShowPayload]:
    return payload.get(_STAGE_KEY) != _HOLDER_STAGE


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


@pytest.mark.spec(_SPEC, "UC-WM1")
def test_todo_show_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"slug": "feature-x"})

    monkeypatch.setattr(_todo_show, "resolve_invocation_cwd", lambda: project_root, raising=False)
    monkeypatch.setattr(_todo_show, "tool_api_request", tool_api_request)

    _todo_show._handle_todo_show(["feature-x"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM2")
def test_artifacts_list_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"artifacts": ["prd"]})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_artifacts_list(["feature-x"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM3")
def test_artifacts_read_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"content": "body"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_artifacts_read(["feature-x", "prd"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM4")
def test_todo_reactivate_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"slug": "feature-x"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_reactivate(["feature-x"])

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert Path(json_body["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM1")
async def test_show_payload_classifies_kindless_todo_without_lifecycle_phase(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo("classify-me")
    await todos_db.write_state("classify-me", {"schema_version": 4, "kind": None, "phase": "pending"})

    payload = await assemble_show_payload(todos_db, "classify-me")

    assert payload is not None
    assert _is_todo_show_payload(payload)
    assert {
        "stage": payload["stage"],
        "current": payload["current"],
        "state": payload["state"],
    } == snapshot


@pytest.mark.spec(_SPEC, "UC-WM1")
async def test_show_payload_buckets_diagnose_as_prepare(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo("diagnose-me")
    await todos_db.write_state(
        "diagnose-me",
        {
            "schema_version": 4,
            "kind": "bug",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.DIAGNOSE.value,
        },
    )

    payload = await assemble_show_payload(todos_db, "diagnose-me")

    assert payload is not None
    assert _is_todo_show_payload(payload)
    assert {"stage": payload["stage"], "current": payload["current"]} == snapshot


@pytest.mark.spec(_SPEC, "UC-WM1")
async def test_todo_projection_includes_kindless_todo_without_lifecycle_phase(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo("classify-me")
    await todos_db.write_state("classify-me", {"schema_version": 4, "kind": None, "phase": "pending"})

    [todo] = assemble_todo_from_db(str(project_root))

    assert {
        "slug": todo.slug,
        "status": todo.status,
        "kind": todo.kind,
        "lifecycle_phase": todo.lifecycle_phase,
        "build_status": todo.build_status,
        "review_status": todo.review_status,
    } == snapshot


@pytest.mark.spec("project/spec/domain/workflow", "UC-WFL-21")
async def test_todo_projection_and_show_payload_include_hold_and_active_runner(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo("held-work")
    await todos_db.write_state(
        "held-work",
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value,
            "hold": True,
            "hold_audit": {"source": _HOLD_SOURCE_MANUAL, "set_at": "2026-06-15T00:00:00+00:00"},
            "active_runner": _ACTIVE_RUNNER,
        },
    )

    [todo] = assemble_todo_from_db(str(project_root))
    assert todo.hold is True
    assert todo.hold_source == _HOLD_SOURCE_MANUAL
    assert todo.active_runner == _ACTIVE_RUNNER

    payload = await assemble_show_payload(todos_db, "held-work")
    assert payload is not None
    assert _is_todo_show_payload(payload)
    assert payload["state"]["hold"] is True
    assert payload["state"]["active_runner"] == _ACTIVE_RUNNER


@pytest.mark.spec(_SPEC, "UC-WM6")
async def test_todo_projection_skips_stateless_non_holder_rows(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(_STATELESS_ANCHOR)
    await todos_db.add_to_todo(_DEPENDENT_CHILD, after=[_STATELESS_ANCHOR])
    await todos_db.write_state(
        _DEPENDENT_CHILD,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
        },
    )

    by_slug = {todo.slug: todo for todo in assemble_todo_from_db(str(project_root))}

    assert _STATELESS_ANCHOR not in by_slug
    assert _DEPENDENT_CHILD in by_slug


@pytest.mark.spec(_SPEC, "UC-WM7")
async def test_todo_projection_keeps_stateless_group_holders(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(_STRUCTURAL_HOLDER)
    await todos_db.add_to_todo(_STRUCTURAL_CHILD, group_slug=_STRUCTURAL_HOLDER)
    await todos_db.write_state(
        _STRUCTURAL_CHILD,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PREPARED.value,
        },
    )

    by_slug = {todo.slug: todo for todo in assemble_todo_from_db(str(project_root))}
    holder = by_slug[_STRUCTURAL_HOLDER]

    assert holder.status == TodoStatus.READY
    assert holder.kind is None
    assert holder.lifecycle_phase is None
    assert holder.build_status is None
    assert holder.review_status is None


@pytest.mark.spec(_SPEC, "UC-WM8")
async def test_show_payload_resolves_stateless_group_holder(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(_STRUCTURAL_HOLDER)
    await todos_db.write_artifact(_STRUCTURAL_HOLDER, _INPUT_ARTIFACT, _HOLDER_INPUT)
    await todos_db.add_to_todo(_STRUCTURAL_CHILD, group_slug=_STRUCTURAL_HOLDER)
    await todos_db.write_state(
        _STRUCTURAL_CHILD,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
        },
    )

    payload = await assemble_show_payload(todos_db, _STRUCTURAL_HOLDER, include_artifact_content=True)

    assert payload is not None
    assert set(payload) == _HOLDER_STRUCTURAL_KEYS
    assert _TODO_LIFECYCLE_PAYLOAD_KEYS.isdisjoint(payload)
    assert payload["slug"] == _STRUCTURAL_HOLDER
    assert payload["stage"] == _HOLDER_STAGE
    assert payload["roadmap"][_CHILDREN_KEY] == [_STRUCTURAL_CHILD]
    assert payload["artifacts"] == [_INPUT_ARTIFACT]
    assert payload["artifact_content"] == {_INPUT_ARTIFACT: _HOLDER_INPUT}
