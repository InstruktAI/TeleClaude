"""Functional tests bound to the workflow artifact-versioning spec."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.todo_routes import write_artifact
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.constants import (
    ARTIFACT_BUG,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
)
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todo_kind import TODO_KIND_CHANGE

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/artifact-versioning"
_PREPARE_ORCHESTRATOR = "prepare-orchestrator-session"
_OTHER_SESSION = "dispatched-worker-session"
_ORIGINAL_PRD = "# Original PRD"
_POISONED_PRD = "# Poisoned PRD"
_APPROVED_PRD = "# Approved PRD"
_ORIGINAL_INPUT = "# Original input"
_INPUT_V2 = "# v2 input"
_LEGACY_UPDATED_BY_PLACEHOLDER = "api.todo.write_artifact"
_OK_STATUS = "ok"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


def _identity(session_id: str) -> CallerIdentity:
    """An agent-session caller identity bound to ``session_id``."""
    return CallerIdentity(
        session_id=session_id,
        system_role=None,
        human_role=None,
        tmux_session_name=None,
    )


async def _todo_in_stage(
    project_root: Path,
    slug: str,
    *,
    lifecycle_phase: str,
    active_runner: str,
) -> TodosDb:
    """Create an active todo bound to ``active_runner`` at ``lifecycle_phase``."""
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(slug)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 5,
            "kind": TODO_KIND_CHANGE,
            "phase": "in_progress",
            "lifecycle_phase": lifecycle_phase,
            "active_runner": active_runner,
        },
    )
    return todos_db


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV7")
async def test_api_refuses_retired_bug_artifact_writes(snapshot: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug="my-bug",
            name=ARTIFACT_BUG,
            content="# Bug content",
            cwd="/path-not-used-before-validation",
        )

    exc = exc_info.value
    assert {"status_code": exc.status_code, "detail": exc.detail} == snapshot


@pytest.mark.spec(_SPEC, "UC-WAV8")
def test_cli_refuses_retired_bug_artifact_writes_before_api_call(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: object,
) -> None:
    def fail_tool_api_request(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("workflow API should not be called for retired artifact writes")

    monkeypatch.setattr(sys, "argv", ["telec", "todo", "artifacts", "write", "my-bug", ARTIFACT_BUG, "# Bug"])
    monkeypatch.setattr(todo_handler, "tool_api_request", fail_tool_api_request)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert {"stdout": captured.out, "stderr": captured.err} == snapshot


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV9")
async def test_worker_write_to_prepare_artifact_is_refused(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav9"
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        active_runner=_PREPARE_ORCHESTRATOR,
    )
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_PREPARE_ORCHESTRATOR)

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_PRD,
            content=_POISONED_PRD,
            cwd=str(project_root),
            identity=_identity(_OTHER_SESSION),
        )

    assert exc_info.value.status_code == 403
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _ORIGINAL_PRD


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV10")
async def test_work_orchestrator_write_to_prepare_artifact_is_refused(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav10"
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.BUILD_STARTED.value,
        active_runner=_PREPARE_ORCHESTRATOR,
    )
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, _ORIGINAL_INPUT, updated_by=_PREPARE_ORCHESTRATOR)

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_INPUT,
            content=_INPUT_V2,
            cwd=str(project_root),
            identity=_identity(_PREPARE_ORCHESTRATOR),
        )

    assert exc_info.value.status_code == 403
    assert await todos_db.read_artifact(slug, ARTIFACT_INPUT) == _ORIGINAL_INPUT


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
@pytest.mark.spec(_SPEC, "UC-WAV12")
async def test_prepare_orchestrator_write_records_resolved_principal(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav11"
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        active_runner=_PREPARE_ORCHESTRATOR,
    )

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_PRD,
        content=_APPROVED_PRD,
        cwd=str(project_root),
        identity=_identity(_PREPARE_ORCHESTRATOR),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _APPROVED_PRD
    metadata = {row["name"]: row["updated_by"] for row in await todos_db.artifact_metadata(slug)}
    assert metadata[ARTIFACT_PRD] == _PREPARE_ORCHESTRATOR
    assert metadata[ARTIFACT_PRD] != _LEGACY_UPDATED_BY_PLACEHOLDER


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
async def test_prepare_orchestrator_writes_input_even_when_requirements_exist(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    slug = "guard-input-regression"
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        active_runner=_PREPARE_ORCHESTRATOR,
    )
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, _ORIGINAL_INPUT, updated_by=_PREPARE_ORCHESTRATOR)
    await todos_db.write_artifact(slug, ARTIFACT_REQUIREMENTS, "# legacy requirements", updated_by="legacy")

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_INPUT,
        content=_INPUT_V2,
        cwd=str(project_root),
        identity=_identity(_PREPARE_ORCHESTRATOR),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_INPUT) == _INPUT_V2
