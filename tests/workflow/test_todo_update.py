"""Functional tests for the unified todo update facade."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from syrupy.assertion import SnapshotAssertion

from teleclaude.api import todo_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.cli.telec.handlers import todo as todo_handlers
from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine.rename import execute_todo_rename
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_CHANGE, TODO_KIND_FEATURE, TODO_KIND_TASK

pytestmark = pytest.mark.functional

_TODO_MANAGEMENT_SPEC = "project/spec/feature/workflow/todo-management"
_DEPENDENCY_GRAPH_SPEC = "project/spec/feature/workflow/dependency-graph"
_TODO_LIFECYCLE_PHASE_SPEC = "project/spec/feature/workflow/todo-lifecycle-phase"
_ARTIFACT_VERSIONING_SPEC = "project/spec/feature/workflow/artifact-versioning"
_MY_TODO = "my-todo"
_NEW_SLUG = "new-slug"
_PARENT_A = "parent-a"
_PARENT_B = "parent-b"
_OPERATION_ID = "op-1"
_ARTIFACT_FIRST = "first"
_ARTIFACT_SECOND = "second"
_ORIGINAL_INPUT = "original input"
_SEEDED_PLAN_BODY = "seeded plan body"


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
    kind: str = TODO_KIND_CHANGE,
    lifecycle_phase: LifecyclePhase = LifecyclePhase.PLAN_DRAFTING,
    after: list[str] | None = None,
    build_started: bool = False,
) -> None:
    await todos_db.add_to_roadmap(slug, after=after)
    state: dict[str, StateValue] = {
        "schema_version": 4,
        "kind": kind,
        "phase": "pending",
        "lifecycle_phase": lifecycle_phase.value,
    }
    if build_started:
        state["build_start_base_sha"] = "abc123"
        state["lifecycle_phase"] = LifecyclePhase.BUILD_STARTED.value
    await todos_db.write_state(slug, state)


def _identity() -> CallerIdentity:
    return CallerIdentity(
        session_id="test-session",
        system_role="worker",
        human_role=None,
        tmux_session_name=None,
    )


class _FakeOperationsService:
    def __init__(self) -> None:
        self.rename_calls: list[dict[str, str | None]] = []

    async def submit_todo_rename(
        self,
        *,
        old_slug: str,
        new_slug: str,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> dict[str, str | int]:
        self.rename_calls.append(
            {
                "old_slug": old_slug,
                "new_slug": new_slug,
                "cwd": cwd,
                "caller_session_id": caller_session_id,
                "client_request_id": client_request_id,
            }
        )
        return {
            "operation_id": _OPERATION_ID,
            "kind": "todo_rename",
            "state": "queued",
            "poll_after_ms": 250,
            "slug": old_slug,
        }


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_cli_sends_each_leg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    todo_handlers._handle_todo_update(
        [_MY_TODO, "--slug", _NEW_SLUG, "--after", _PARENT_A, "--after", _PARENT_B, "--kind", "bug", "--force"]
    )

    assert tool_api_call.call_args.args[:2] == ("POST", "/todos/update")
    body = tool_api_call.call_args.kwargs["json_body"]
    assert body["slug"] == _MY_TODO
    assert body["new_slug"] == _NEW_SLUG
    assert body["after"] == [_PARENT_A, _PARENT_B]
    assert body["kind"] == TODO_KIND_BUG
    assert body["force"] is True
    assert Path(body["cwd"]) == project_root
    assert isinstance(body["client_request_id"], str)


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_retired_todo_mutation_verbs_are_rejected() -> None:
    with pytest.raises(SystemExit):
        todo_handlers._handle_todo(["rename", "my-todo", "new-slug"])
    with pytest.raises(SystemExit):
        todo_handlers._handle_todo(["set-deps", "my-todo", "--after", "parent"])


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
async def test_todo_update_slug_leg_returns_rename_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, _MY_TODO)
    fake_operations = _FakeOperationsService()

    monkeypatch.setattr(todo_routes, "get_operations_service", lambda: fake_operations)

    receipt = await todo_routes.todo_update(
        slug=_MY_TODO,
        new_slug=_NEW_SLUG,
        cwd=str(project_root),
        client_request_id="request-1",
        identity=_identity(),
    )

    assert isinstance(receipt, dict)
    assert receipt["operation_id"] == _OPERATION_ID
    assert fake_operations.rename_calls == [
        {
            "old_slug": _MY_TODO,
            "new_slug": _NEW_SLUG,
            "cwd": str(project_root),
            "caller_session_id": "test-session",
            "client_request_id": "request-1",
        }
    ]


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
async def test_rename_engine_preserves_artifacts_versions_and_deps(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "old-slug")
    await _add_todo(todos_db, "parent")
    await todos_db.set_deps("old-slug", after=["parent"])
    await todos_db.write_artifact("old-slug", ARTIFACT_INPUT, _ARTIFACT_FIRST, updated_by="test")
    await todos_db.write_artifact("old-slug", ARTIFACT_INPUT, _ARTIFACT_SECOND, updated_by="test")
    daemon_db = Db(str(tmp_path / "daemon.db"))
    await daemon_db.initialize()

    result = await execute_todo_rename(daemon_db, "old-slug", "new-slug", str(project_root))

    assert result
    assert not await todos_db.slug_in_roadmap("old-slug")
    assert await todos_db.slug_in_roadmap("new-slug")
    assert await todos_db.read_artifact("new-slug", ARTIFACT_INPUT) == _ARTIFACT_SECOND
    assert [version["content"] for version in await todos_db.artifact_versions("new-slug", ARTIFACT_INPUT)] == [
        _ARTIFACT_SECOND,
        _ARTIFACT_FIRST,
    ]
    assert (await todos_db.load_deps())["new-slug"] == ["parent"]


@pytest.mark.spec(_DEPENDENCY_GRAPH_SPEC, "UC-WDG4")
async def test_todo_update_after_replaces_dependencies_and_validates_cycles(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "feature-a")
    await _add_todo(todos_db, "feature-b")
    await _add_todo(todos_db, "feature-c")

    response = await todo_routes.todo_update(
        slug="feature-a",
        after=["feature-b", "feature-c"],
        cwd=str(project_root),
        identity=_identity(),
    )

    sync_response = cast(todo_routes._TodoUpdateResponse, response)
    assert sync_response.after == ["feature-b", "feature-c"]
    assert (await todos_db.load_deps())["feature-a"] == ["feature-b", "feature-c"]

    with pytest.raises(HTTPException) as missing:
        await todo_routes.todo_update(slug="feature-a", after=["ghost"], cwd=str(project_root), identity=_identity())
    assert missing.value.status_code == 404

    await todos_db.set_deps("feature-b", after=["feature-a"])
    with pytest.raises(HTTPException) as cycle:
        await todo_routes.todo_update(
            slug="feature-a", after=["feature-b"], cwd=str(project_root), identity=_identity()
        )
    assert cycle.value.status_code == 409
    assert cycle.value.detail == snapshot


@pytest.mark.spec(_TODO_LIFECYCLE_PHASE_SPEC, "UC-TLP1")
async def test_todo_update_kind_warns_then_forces_orphan_removal(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(
        todos_db,
        "feature-work",
        kind=TODO_KIND_FEATURE,
        lifecycle_phase=LifecyclePhase.PRD_DRAFTING,
    )
    await todos_db.write_artifact("feature-work", ARTIFACT_PRD, "prd", updated_by="test")
    await todos_db.write_artifact("feature-work", ARTIFACT_ARCHITECTURE, "architecture", updated_by="test")

    with pytest.raises(HTTPException) as warning:
        await todo_routes.todo_update(
            slug="feature-work",
            kind=TODO_KIND_BUG,
            cwd=str(project_root),
            identity=_identity(),
        )
    assert warning.value.status_code == 409
    assert warning.value.detail == snapshot(name="orphan_warning")

    response = await todo_routes.todo_update(
        slug="feature-work",
        kind=TODO_KIND_BUG,
        force=True,
        cwd=str(project_root),
        identity=_identity(),
    )

    state = await todos_db.read_state("feature-work")
    assert state is not None
    assert state["kind"] == TODO_KIND_BUG
    assert state["lifecycle_phase"] == LifecyclePhase.DIAGNOSE.value
    sync_response = cast(todo_routes._TodoUpdateResponse, response)
    assert sync_response.kind == TODO_KIND_BUG
    assert sync_response.lifecycle_phase == LifecyclePhase.DIAGNOSE.value
    assert not await todos_db.artifact_exists("feature-work", ARTIFACT_PRD)
    assert not await todos_db.artifact_exists("feature-work", ARTIFACT_ARCHITECTURE)
    assert sync_response.warnings == snapshot(name="force_warnings")


@pytest.mark.spec(_ARTIFACT_VERSIONING_SPEC, "UC-WAV4")
async def test_todo_update_kind_folds_seeded_plan_for_task(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "planned-change")
    await todos_db.write_artifact("planned-change", ARTIFACT_INPUT, _ORIGINAL_INPUT, updated_by="test")
    await todos_db.write_artifact(
        "planned-change",
        ARTIFACT_IMPLEMENTATION_PLAN,
        _SEEDED_PLAN_BODY,
        updated_by="test",
    )

    response = await todo_routes.todo_update(
        slug="planned-change",
        kind=TODO_KIND_TASK,
        force=True,
        cwd=str(project_root),
        identity=_identity(),
    )

    state = await todos_db.read_state("planned-change")
    assert state is not None
    assert state["kind"] == TODO_KIND_TASK
    assert state["lifecycle_phase"] == LifecyclePhase.PREPARED.value
    assert await todos_db.read_artifact("planned-change", ARTIFACT_INPUT) == snapshot
    assert not await todos_db.artifact_exists("planned-change", ARTIFACT_IMPLEMENTATION_PLAN)
    sync_response = cast(todo_routes._TodoUpdateResponse, response)
    assert sync_response.folded_artifact == ARTIFACT_IMPLEMENTATION_PLAN


@pytest.mark.spec(_TODO_LIFECYCLE_PHASE_SPEC, "UC-TLP1")
async def test_todo_update_kind_keeps_implementation_plan_for_sdlc_kinds(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "planned-change")
    await todos_db.write_artifact(
        "planned-change",
        ARTIFACT_IMPLEMENTATION_PLAN,
        "plan body",
        updated_by="test",
    )

    await todo_routes.todo_update(
        slug="planned-change",
        kind=TODO_KIND_FEATURE,
        force=True,
        cwd=str(project_root),
        identity=_identity(),
    )

    state = await todos_db.read_state("planned-change")
    assert state is not None
    assert state["kind"] == TODO_KIND_FEATURE
    assert state["lifecycle_phase"] == LifecyclePhase.PRD_DRAFTING.value
    assert await todos_db.artifact_exists("planned-change", ARTIFACT_IMPLEMENTATION_PLAN)


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
async def test_todo_update_refuses_slug_and_kind_after_build_but_allows_after(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_todo(todos_db, "build-work", build_started=True)
    await _add_todo(todos_db, "parent")

    with pytest.raises(HTTPException) as slug_gate:
        await todo_routes.todo_update(
            slug="build-work",
            new_slug="renamed-work",
            cwd=str(project_root),
            identity=_identity(),
        )
    assert slug_gate.value.status_code == 409

    with pytest.raises(HTTPException) as kind_gate:
        await todo_routes.todo_update(
            slug="build-work",
            kind=TODO_KIND_TASK,
            cwd=str(project_root),
            identity=_identity(),
        )
    assert kind_gate.value.status_code == 409

    response = await todo_routes.todo_update(
        slug="build-work",
        after=["parent"],
        cwd=str(project_root),
        identity=_identity(),
    )

    sync_response = cast(todo_routes._TodoUpdateResponse, response)
    assert sync_response.after == ["parent"]
    state = await todos_db.read_state("build-work")
    assert state is not None
    assert state["kind"] == TODO_KIND_CHANGE
    assert state["lifecycle_phase"] == LifecyclePhase.BUILD_STARTED.value
    assert (await todos_db.load_deps())["build-work"] == ["parent"]


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_after_csv_expands_to_individual_slugs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    todo_handlers._handle_todo_update([_MY_TODO, "--after", f"{_PARENT_A},{_PARENT_B}"])

    body = tool_api_call.call_args.kwargs["json_body"]
    assert body["after"] == [_PARENT_A, _PARENT_B]


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_after_repeated_flags_sends_same_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    todo_handlers._handle_todo_update([_MY_TODO, "--after", _PARENT_A, "--after", _PARENT_B])

    body = tool_api_call.call_args.kwargs["json_body"]
    assert body["after"] == [_PARENT_A, _PARENT_B]


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_after_empty_string_sends_empty_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    todo_handlers._handle_todo_update([_MY_TODO, "--after", ""])

    body = tool_api_call.call_args.kwargs["json_body"]
    assert body["after"] == []


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_after_mixed_empty_and_nonempty_fails_before_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    with pytest.raises(SystemExit):
        todo_handlers._handle_todo_update([_MY_TODO, "--after", "", "--after", _PARENT_A])

    tool_api_call.assert_not_called()


@pytest.mark.spec(_TODO_MANAGEMENT_SPEC, "UC-WM5")
def test_todo_update_after_empty_csv_segment_fails_before_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_call = MagicMock(return_value={"status": "ok"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_call", tool_api_call)

    with pytest.raises(SystemExit):
        todo_handlers._handle_todo_update([_MY_TODO, "--after", f"{_PARENT_A},,{_PARENT_B}"])

    tool_api_call.assert_not_called()
