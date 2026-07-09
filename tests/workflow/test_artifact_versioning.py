"""Functional tests bound to the workflow artifact-versioning spec."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import HTTPException

from teleclaude.api import todo_artifact_authority as authority_mod
from teleclaude.api.auth import CallerIdentity
from teleclaude.api.todo_routes import read_artifact, write_artifact
from teleclaude.cli.telec import main
from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.constants import (
    ARTIFACT_BUG,
    ARTIFACT_INPUT,
    ARTIFACT_LOG,
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
from teleclaude.project_root import resolve_project_root
from teleclaude.types.todo_kind import TODO_KIND_CHANGE, TODO_KIND_TASK

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
    """An isolated runtime sessions registry, bound into the role gate.

    The prepare-artifact gate reads the caller's session job through the
    module-level ``runtime_db`` in the authority module; swap it to a fresh
    in-memory Db so tests drive real session rows.
    """
    test_db = Db(":memory:")
    await test_db.initialize()
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
        project_path=str(resolve_project_root(project_root)),
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
    await todos_db.add_to_todo(slug, lineage="human:test@example.com")
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
async def test_write_to_slug_with_different_live_active_runner_is_refused(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav10"
    # The slug's active_runner names a different, live session.
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        active_runner=_OTHER_DRIVER,
    )
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_OTHER_DRIVER)
    await _register_session(
        runtime_db,
        _OTHER_DRIVER,
        job=JobRole.PREPARE_ORCHESTRATOR.value,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=slug,
        project_root=project_root,
    )
    # The caller is a role-permitted prepare orchestrator, but is not the claimant.
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
    assert await _active_runner(todos_db, slug) == _OTHER_DRIVER


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV22")
async def test_claimants_own_write_to_its_claimed_slug_is_accepted(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-wav22"
    # The slug's active_runner is the caller's own live session.
    todos_db = await _todo_in_stage(
        project_root,
        slug,
        lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        active_runner=_PREPARE_ORCHESTRATOR,
    )
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_PREPARE_ORCHESTRATOR)
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
    assert len(await todos_db.artifact_versions(slug, ARTIFACT_PRD)) == 2


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV11")
@pytest.mark.spec(_SPEC, "UC-WAV12")
async def test_prepare_orchestrator_write_to_unclaimed_slug_records_principal_without_claim(
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
    assert not await _active_runner(todos_db, slug)
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
@pytest.mark.spec(_SPEC, "UC-WAV20")
async def test_prepare_artifact_write_accepts_writer_bound_to_other_slug(tmp_path: Path, runtime_db: Db) -> None:
    project_root = tmp_path / "project"
    slug = "guard-bound"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    await todos_db.write_artifact(slug, ARTIFACT_PRD, _ORIGINAL_PRD, updated_by=_PREPARE_ORCHESTRATOR)
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
    assert not await _active_runner(todos_db, slug)
    assert len(await todos_db.artifact_versions(slug, ARTIFACT_PRD)) == 2


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
    assert not await _active_runner(todos_db, slug)


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV21")
async def test_two_competing_unclaimed_writers_yield_two_versions_and_no_claim(
    tmp_path: Path, runtime_db: Db, cluster_event_bus: None
) -> None:
    del cluster_event_bus
    project_root = tmp_path / "project"
    slug = "guard-race"
    todos_db = await _todo_in_stage(project_root, slug, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value)
    # Two role-permitted writers, neither holding a claim yet, race to append versions.
    for writer in (_RACE_WRITER_A, _RACE_WRITER_B):
        await _register_session(
            runtime_db,
            writer,
            job=JobRole.PREPARE_ORCHESTRATOR.value,
            system_role=ROLE_ORCHESTRATOR,
            working_slug=None,
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

    assert statuses == [200, 200]
    versions = await todos_db.artifact_versions(slug, ARTIFACT_PRD)
    assert len(versions) == 2
    assert not await _active_runner(todos_db, slug)


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-WAV19")
async def test_log_artifact_round_trips_and_reads_empty_before_first_write(tmp_path: Path) -> None:
    """A kind=task todo's `log` reads empty before first write, then round-trips.

    Binds the run-task continuity contract: the lane reads the log on start
    (empty on the first firing, no kind-validation error) and appends dated
    entries that the versioned store records.
    """
    project_root = tmp_path / "project"
    slug = "log-wav19"
    await close_todos_db_instances()
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(slug, lineage="human:test@example.com")
    await todos_db.write_state(
        slug,
        {
            "schema_version": 5,
            "kind": TODO_KIND_TASK,
            "phase": "in_progress",
            "lifecycle_phase": LifecyclePhase.BUILD_STARTED.value,
            "active_runner": "",
        },
    )

    # First firing: reading the log before any write returns empty content,
    # not the "Unknown artifact kind: log" rejection the closed enum produced.
    first_read = await read_artifact(slug=slug, name=ARTIFACT_LOG, cwd=str(project_root))
    assert not first_read.content

    entry_one = "## 2026-06-25\n- started task; no prior state."
    write_one = await write_artifact(
        slug=slug,
        name=ARTIFACT_LOG,
        content=entry_one,
        cwd=str(project_root),
        identity=_agent_identity("runner-session"),
    )
    assert write_one.status == _OK_STATUS
    assert (await read_artifact(slug=slug, name=ARTIFACT_LOG, cwd=str(project_root))).content == entry_one

    # A second firing appends; the read-modify-write lands a new version.
    entry_two = f"{entry_one}\n## 2026-06-26\n- resumed; completed step 1."
    await write_artifact(
        slug=slug,
        name=ARTIFACT_LOG,
        content=entry_two,
        cwd=str(project_root),
        identity=_agent_identity("runner-session"),
    )
    assert (await read_artifact(slug=slug, name=ARTIFACT_LOG, cwd=str(project_root))).content == entry_two
    assert len(await todos_db.artifact_versions(slug, ARTIFACT_LOG)) == 2
