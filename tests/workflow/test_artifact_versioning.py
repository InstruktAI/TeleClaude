"""Functional tests bound to the workflow artifact-versioning spec."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import HTTPException

from teleclaude.api import todo_artifact_authority as authority_mod
from teleclaude.api import todo_routes as routes_mod
from teleclaude.api.auth import CallerIdentity
from teleclaude.api.todo_routes import write_artifact
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.constants import (
    ARTIFACT_BUG,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
    JobRole,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.project_root import resolve_state_root
from teleclaude.types.todo_kind import TODO_KIND_CHANGE

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/artifact-versioning"
_PREPARE_ORCHESTRATOR = "prepare-orchestrator-session"
_OTHER_DRIVER = "other-driver-session"
_WORKER_SESSION = "dispatched-worker-session"
_WORK_ORCHESTRATOR = "work-orchestrator-session"
_ROLELESS_SESSION = "roleless-operator-session"
_ORIGINAL_PRD = "# Original PRD"
_POISONED_PRD = "# Poisoned PRD"
_APPROVED_PRD = "# Approved PRD"
_ORIGINAL_INPUT = "# Original input"
_INPUT_V2 = "# v2 input"
_HUMAN_INPUT = "# Human-refined input"
_HUMAN_EMAIL = "human@example.test"
_HUMAN_PRINCIPAL = f"human:{_HUMAN_EMAIL}"
_LEGACY_UPDATED_BY_PLACEHOLDER = "api.todo.write_artifact"
_OK_STATUS = "ok"
_RACE_WRITER_A = "race-writer-a"
_RACE_WRITER_B = "race-writer-b"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


@pytest.fixture
async def runtime_db(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Db, None]:
    """An isolated runtime sessions registry, bound into the write boundary.

    The prepare-artifact gate reads the sessions registry (caller job, live
    holder) through the module-level ``runtime_db`` in the route and authority
    modules; swap both to a fresh in-memory Db so tests drive real session rows.
    """
    test_db = Db(":memory:")
    await test_db.initialize()
    monkeypatch.setattr(routes_mod, "runtime_db", test_db)
    monkeypatch.setattr(authority_mod, "runtime_db", test_db)
    yield test_db


def _agent_identity(session_id: str) -> CallerIdentity:
    """A TeleClaude-session caller identity bound to ``session_id``."""
    return CallerIdentity(
        session_id=session_id,
        system_role=None,
        human_role=None,
        tmux_session_name=None,
    )


def _human_identity() -> CallerIdentity:
    """A direct human-identity caller (no session id, verified human principal)."""
    return CallerIdentity(
        session_id="",
        system_role=None,
        human_role="admin",
        tmux_session_name=None,
        email=_HUMAN_EMAIL,
    )


async def _register_session(
    db: Db,
    session_id: str,
    *,
    job: str | None,
    system_role: str | None,
    working_slug: str | None,
    project_root: Path,
) -> None:
    """Insert a live session row into the runtime registry."""
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tmux-{session_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=f"/session {session_id}",
        system_role=system_role,
        job=job,
        working_slug=working_slug,
        project_path=str(resolve_state_root(project_root)),
        session_id=session_id,
        emit_session_started=False,
    )


async def _todo_in_stage(
    project_root: Path,
    slug: str,
    *,
    lifecycle_phase: str,
    active_runner: str = "",
) -> TodosDb:
    """Create an active todo at ``lifecycle_phase`` with an optional claim."""
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


async def _active_runner(todos_db: TodosDb, slug: str) -> str:
    state = await todos_db.read_state(slug)
    assert state is not None
    return str(state.get("active_runner") or "")


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
async def test_worker_write_to_prepare_artifact_is_refused_by_role(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav9"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_PREPARE_ORCHESTRATOR)
    await _register_session(
        runtime_db,
        _WORKER_SESSION,
        job=JobRole.BUILDER.value,
        system_role=ROLE_WORKER,
        working_slug=slug,
        project_root=project_root,
    )

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_PRD,
            content=_POISONED_PRD,
            cwd=str(project_root),
            identity=_agent_identity(_WORKER_SESSION),
        )

    assert exc_info.value.status_code == 403
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _ORIGINAL_PRD


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV15")
async def test_work_orchestrator_write_to_prepare_artifact_is_refused_by_role(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav15"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.BUILD_STARTED.value)
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, _ORIGINAL_INPUT, updated_by=_PREPARE_ORCHESTRATOR)
    await _register_session(
        runtime_db,
        _WORK_ORCHESTRATOR,
        job=JobRole.WORK_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=slug,
        project_root=project_root,
    )

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_INPUT,
            content=_INPUT_V2,
            cwd=str(project_root),
            identity=_agent_identity(_WORK_ORCHESTRATOR),
        )

    assert exc_info.value.status_code == 403
    assert await todos_db.read_artifact(slug, ARTIFACT_INPUT) == _ORIGINAL_INPUT


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV10")
async def test_write_to_slug_driven_by_different_live_session_is_refused(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav10"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_OTHER_DRIVER)
    # The other live orchestrator drives the slug (its working_slug == slug).
    await _register_session(
        runtime_db,
        _OTHER_DRIVER,
        job=JobRole.PREPARE_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=slug,
        project_root=project_root,
    )
    # The caller is a role-permitted prepare orchestrator not bound to this slug.
    await _register_session(
        runtime_db,
        _PREPARE_ORCHESTRATOR,
        job=JobRole.PREPARE_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug="some-other-slug",
        project_root=project_root,
    )

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_PRD,
            content=_POISONED_PRD,
            cwd=str(project_root),
            identity=_agent_identity(_PREPARE_ORCHESTRATOR),
        )

    assert exc_info.value.status_code == 409
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _ORIGINAL_PRD


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
@pytest.mark.spec(_SPEC, "UC-WAV12")
async def test_prepare_orchestrator_write_to_unclaimed_slug_claims_and_records_principal(
    tmp_path: Path, runtime_db: Db
) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav11"
    # Parked at the PRD gate with no live claim — the exact state the old gate broke.
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    await _register_session(
        runtime_db,
        _PREPARE_ORCHESTRATOR,
        job=JobRole.PREPARE_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=slug,
        project_root=project_root,
    )

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_PRD,
        content=_APPROVED_PRD,
        cwd=str(project_root),
        identity=_agent_identity(_PREPARE_ORCHESTRATOR),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _APPROVED_PRD
    assert await _active_runner(todos_db, slug) == _PREPARE_ORCHESTRATOR
    metadata = {row["name"]: row["updated_by"] for row in await todos_db.artifact_metadata(slug)}
    assert metadata[ARTIFACT_PRD] == _PREPARE_ORCHESTRATOR
    assert metadata[ARTIFACT_PRD] != _LEGACY_UPDATED_BY_PLACEHOLDER


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV16")
async def test_human_identity_write_to_unclaimed_slug_is_accepted_without_claiming(
    tmp_path: Path, runtime_db: Db
) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav16"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_INPUT,
        content=_HUMAN_INPUT,
        cwd=str(project_root),
        identity=_human_identity(),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_INPUT) == _HUMAN_INPUT
    assert not await _active_runner(todos_db, slug)
    metadata = {row["name"]: row["updated_by"] for row in await todos_db.artifact_metadata(slug)}
    assert metadata[ARTIFACT_INPUT] == _HUMAN_PRINCIPAL


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV17")
async def test_roleless_session_write_to_unheld_slug_claims_the_slug(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav17"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    # A registered TeleClaude session that carries no job role — the operator-driven shape.
    await _register_session(
        runtime_db,
        _ROLELESS_SESSION,
        job=None,
        system_role=None,
        working_slug="some-other-slug",
        project_root=project_root,
    )

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_PRD,
        content=_APPROVED_PRD,
        cwd=str(project_root),
        identity=_agent_identity(_ROLELESS_SESSION),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _APPROVED_PRD
    assert await _active_runner(todos_db, slug) == _ROLELESS_SESSION
    metadata = {row["name"]: row["updated_by"] for row in await todos_db.artifact_metadata(slug)}
    assert metadata[ARTIFACT_PRD] == _ROLELESS_SESSION


@pytest.mark.asyncio
async def test_unregistered_session_write_to_prepare_artifact_is_refused(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-unknown"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    # No session row is registered for this id — an unknown caller, not a roleless session.

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_PRD,
            content=_POISONED_PRD,
            cwd=str(project_root),
            identity=_agent_identity("ghost-session"),
        )

    assert exc_info.value.status_code == 403
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) != _POISONED_PRD
    assert not await _active_runner(todos_db, slug)


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV18")
async def test_roleless_session_write_to_slug_held_by_other_is_refused(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav18"
    todos_db = await _todo_in_stage(
        project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value, active_runner=_OTHER_DRIVER
    )
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_OTHER_DRIVER)
    # A different live session holds the slug via its active_runner claim.
    await _register_session(
        runtime_db,
        _OTHER_DRIVER,
        job=None,
        system_role=None,
        working_slug=slug,
        project_root=project_root,
    )
    await _register_session(
        runtime_db,
        _ROLELESS_SESSION,
        job=None,
        system_role=None,
        working_slug="some-other-slug",
        project_root=project_root,
    )

    with pytest.raises(HTTPException) as exc_info:
        await write_artifact(
            slug=slug,
            name=ARTIFACT_PRD,
            content=_POISONED_PRD,
            cwd=str(project_root),
            identity=_agent_identity(_ROLELESS_SESSION),
        )

    assert exc_info.value.status_code == 409
    assert await todos_db.read_artifact(slug, ARTIFACT_PRD) == _ORIGINAL_PRD
    assert await _active_runner(todos_db, slug) == _OTHER_DRIVER


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
async def test_prepare_orchestrator_writes_input_even_when_requirements_exist(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-input-regression"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, _ORIGINAL_INPUT, updated_by=_PREPARE_ORCHESTRATOR)
    await todos_db.write_artifact(slug, ARTIFACT_REQUIREMENTS, "# legacy requirements", updated_by="legacy")
    await _register_session(
        runtime_db,
        _PREPARE_ORCHESTRATOR,
        job=JobRole.PREPARE_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=slug,
        project_root=project_root,
    )

    response = await write_artifact(
        slug=slug,
        name=ARTIFACT_INPUT,
        content=_INPUT_V2,
        cwd=str(project_root),
        identity=_agent_identity(_PREPARE_ORCHESTRATOR),
    )

    assert response.status == _OK_STATUS
    assert await todos_db.read_artifact(slug, ARTIFACT_INPUT) == _INPUT_V2


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
async def test_two_competing_unclaimed_writers_yield_one_version_and_one_conflict(
    tmp_path: Path, runtime_db: Db
) -> None:
    project_root = tmp_path / "project"
    slug = "guard-race"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    # Two role-permitted writers, neither bound to the slug, race to claim it.
    for writer in (_RACE_WRITER_A, _RACE_WRITER_B):
        await _register_session(
            runtime_db,
            writer,
            job=JobRole.PREPARE_ORCHESTRATOR.value,
            system_role=ROLE_ORCHESTRATOR,
            working_slug=f"other-{writer}",
            project_root=project_root,
        )

    async def _attempt(writer: str) -> int:
        try:
            await write_artifact(
                slug=slug,
                name=ARTIFACT_PRD,
                content=f"# PRD from {writer}",
                cwd=str(project_root),
                identity=_agent_identity(writer),
            )
        except HTTPException as exc:
            return exc.status_code
        return 200

    statuses = sorted(await asyncio.gather(_attempt(_RACE_WRITER_A), _attempt(_RACE_WRITER_B)))

    assert statuses == [200, 409]
    versions = await todos_db.artifact_versions(slug, ARTIFACT_PRD)
    assert len(versions) == 1
    # Exactly one writer won the claim race; which one is nondeterministic, so the
    # contract is that a claim landed (non-empty active_runner), not its identity.
    assert await _active_runner(todos_db, slug)
