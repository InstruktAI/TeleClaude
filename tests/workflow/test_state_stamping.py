"""Functional tests bound to the workflow state-stamping spec."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from git import Actor, Repo

import teleclaude.core.db as db_mod
from teleclaude.constants import (
    ARTIFACT_PRD,
    ARTIFACT_TASK_PLAN,
    LOCAL_COMPUTER,
    ROLE_ORCHESTRATOR,
    ROLE_WORKER,
    WORKTREE_DIR,
    JobRole,
)
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError, StateWriter
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todo_kind import TODO_KIND_CHANGE, TODO_KIND_FEATURE, TODO_KIND_TASK

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/state-stamping"
_SLUG = "stamp-target"
_NO_BUILD_GATE_CLAIM = ""
_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+")
_HUMAN_SESSION = "human-session"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _add_kindless_todo(todos_db: TodosDb, slug: str) -> None:
    await todos_db.add_to_roadmap(slug)
    await todos_db.write_state(slug, {"schema_version": 4, "kind": None, "phase": "pending"})


async def _add_build_started_todo(todos_db: TodosDb, slug: str, *, active_runner: str | None = None) -> None:
    await todos_db.add_to_roadmap(slug)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": TODO_KIND_CHANGE,
            "phase": "in_progress",
            "lifecycle_phase": LifecyclePhase.BUILD_STARTED.value,
            "active_runner": active_runner,
        },
    )


async def _add_feature_todo_with_prd(todos_db: TodosDb, slug: str) -> None:
    await todos_db.add_to_roadmap(slug)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": TODO_KIND_FEATURE,
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PRD_HUMAN_APPROVAL.value,
        },
    )
    await todos_db.write_artifact(slug, ARTIFACT_PRD, "# PRD\n\nApprove this.", updated_by="test")


async def _create_runtime_session(
    project_root: Path,
    *,
    session_id: str,
    system_role: str | None,
    working_slug: str | None,
    job: str | None = None,
) -> str:
    runtime_db = await db_mod.get_db()
    session = await runtime_db.create_session(
        computer_name=LOCAL_COMPUTER,
        tmux_session_name=f"tmux-{session_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=session_id,
        session_id=session_id,
        system_role=system_role,
        job=job,
        project_path=str(project_root),
        working_slug=working_slug,
        emit_session_started=False,
    )
    return session.session_id


def _create_worktree_with_build_commit(project_root: Path, slug: str) -> None:
    worktree_cwd = project_root / WORKTREE_DIR / slug
    worktree_cwd.mkdir(parents=True)
    repo = Repo.init(worktree_cwd)
    actor = Actor("TeleClaude Test", "test@example.com")

    tracked_file = worktree_cwd / "tracked.txt"
    tracked_file.write_text("base\n", encoding="utf-8")
    repo.index.add([str(tracked_file)])
    base_commit = repo.index.commit("base", author=actor, committer=actor)
    repo.git.update_ref("refs/remotes/origin/main", base_commit.hexsha)

    tracked_file.write_text("base\nbuild\n", encoding="utf-8")
    repo.index.add([str(tracked_file)])
    repo.index.commit("build", author=actor, committer=actor)


@pytest.mark.spec(_SPEC, "UC-WSS2")
async def test_kind_assign_change_fixes_kind_and_entry_phase(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_kindless_todo(todos_db, _SLUG)

    await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="kind_assign", phase=TODO_KIND_CHANGE)

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["kind"] == TODO_KIND_CHANGE
    assert state["lifecycle_phase"] == LifecyclePhase.PLAN_DRAFTING.value
    assert "kind_proposal" not in state


@pytest.mark.spec(_SPEC, "UC-WSS5")
async def test_prd_approval_records_current_artifact_digest(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_feature_todo_with_prd(todos_db, _SLUG)
    old_digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_PRD)
    await todos_db.write_artifact(_SLUG, ARTIFACT_PRD, "# PRD\n\nApprove this current version.", updated_by="test")
    current_digest = await todos_db.artifact_digest(_SLUG, ARTIFACT_PRD)

    await apply_todo_stamp(
        cwd=str(project_root),
        slug=_SLUG,
        stamp_type="prd_approved",
        caller_session_id="human-session",
    )

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    writer = StateWriter(state)
    assert old_digest != current_digest
    assert writer.state.approvals.prd_approved.approved is True
    assert _ISO_TIMESTAMP_RE.fullmatch(writer.state.approvals.prd_approved.approved_at)
    assert writer.state.approvals.prd_approved.approved_digest == current_digest
    assert writer.state.artifacts.prd.digest == current_digest


@pytest.mark.spec(_SPEC, "UC-WSS5")
async def test_approve_current_gate_resolves_prd_gate_and_refuses_without_gate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_feature_todo_with_prd(todos_db, _SLUG)

    await apply_todo_stamp(
        cwd=str(project_root),
        slug=_SLUG,
        stamp_type="approve_current_gate",
        caller_session_id=_HUMAN_SESSION,
    )

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    writer = StateWriter(state)
    assert writer.state.approvals.prd_approved.approved is True
    assert writer.state.approvals.prd_approved.caller_session_id == _HUMAN_SESSION

    await todos_db.add_to_roadmap("no-gate")
    await todos_db.write_state(
        "no-gate",
        {
            "schema_version": 4,
            "kind": TODO_KIND_CHANGE,
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value,
        },
    )
    with pytest.raises(StateMutationError, match="no pending approval gate"):
        await apply_todo_stamp(
            cwd=str(project_root),
            slug="no-gate",
            stamp_type="approve_current_gate",
            caller_session_id=_HUMAN_SESSION,
        )


@pytest.mark.spec(_SPEC, "UC-WSS5")
async def test_approve_current_gate_routes_creative_design_spec_gate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_roadmap(_SLUG)
    # A creative design-spec gate is observable from state: the section exists
    # but its ``confirmed`` flag is not yet set. The lifecycle phase is a regular
    # prepare phase, so this approval is routed solely by the creative section —
    # not by PRD phase.
    await todos_db.write_state(
        _SLUG,
        {
            "schema_version": 4,
            "kind": TODO_KIND_CHANGE,
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value,
            "creative": {"design_spec": {"confirmed": False}},
        },
    )

    await apply_todo_stamp(
        cwd=str(project_root),
        slug=_SLUG,
        stamp_type="approve_current_gate",
        caller_session_id=_HUMAN_SESSION,
    )

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    writer = StateWriter(state)
    creative = writer.state.creative
    assert isinstance(creative, dict)
    design_spec = creative.get("design_spec")
    assert isinstance(design_spec, dict)
    assert design_spec.get("confirmed") is True


@pytest.mark.spec(_SPEC, "UC-WSS1")
async def test_kind_assign_task_writes_task_plan_and_prepared_phase(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_kindless_todo(todos_db, _SLUG)

    await apply_todo_stamp(
        cwd=str(project_root),
        slug=_SLUG,
        stamp_type="kind_assign",
        phase=TODO_KIND_TASK,
        value="Notify the release channel after deploy.",
    )

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["kind"] == TODO_KIND_TASK
    assert state["lifecycle_phase"] == LifecyclePhase.PREPARED.value
    task_plan = await todos_db.read_artifact(_SLUG, ARTIFACT_TASK_PLAN)
    assert _ISO_TIMESTAMP_RE.sub("<timestamp>", task_plan) == snapshot


@pytest.mark.spec(_SPEC, "UC-WSS3")
async def test_kind_assign_refuses_already_kinded_todo(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(
        _SLUG,
        {
            "schema_version": 4,
            "kind": TODO_KIND_CHANGE,
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PLAN_DRAFTING.value,
        },
    )

    with pytest.raises(StateMutationError):
        await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="kind_assign", phase=TODO_KIND_TASK)

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["kind"] == TODO_KIND_CHANGE
    assert state["lifecycle_phase"] == LifecyclePhase.PLAN_DRAFTING.value
    assert not await todos_db.artifact_exists(_SLUG, ARTIFACT_TASK_PLAN)


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_build_complete_accepts_live_active_runner_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    session_id = f"{tmp_path.name}-work-orchestrator"
    await _add_build_started_todo(todos_db, _SLUG, active_runner=session_id)
    _create_worktree_with_build_commit(project_root, _SLUG)
    await _create_runtime_session(
        project_root,
        session_id=session_id,
        system_role=ROLE_ORCHESTRATOR,
        working_slug=None,
        job=JobRole.WORK_ORCHESTRATOR.value,
    )

    await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="build_complete", caller_session_id=session_id)

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert _ISO_TIMESTAMP_RE.fullmatch(state["build_gate_claim_at"])


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_build_complete_still_accepts_owning_worker_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_build_started_todo(todos_db, _SLUG)
    _create_worktree_with_build_commit(project_root, _SLUG)
    session_id = await _create_runtime_session(
        project_root,
        session_id=f"{tmp_path.name}-owning-worker",
        system_role=ROLE_WORKER,
        working_slug=_SLUG,
        job=JobRole.BUILDER.value,
    )

    await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="build_complete", caller_session_id=session_id)

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert _ISO_TIMESTAMP_RE.fullmatch(state["build_gate_claim_at"])


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_build_complete_refuses_unbound_caller_when_todo_has_live_claim(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    claimant_id = f"{tmp_path.name}-claimant"
    await _add_build_started_todo(todos_db, _SLUG, active_runner=claimant_id)
    await _create_runtime_session(
        project_root,
        session_id=claimant_id,
        system_role=ROLE_WORKER,
        working_slug=_SLUG,
        job=JobRole.BUILDER.value,
    )

    with pytest.raises(PermissionError, match=claimant_id):
        await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="build_complete", caller_session_id=None)

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["build_gate_claim_at"] == _NO_BUILD_GATE_CLAIM


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_pre_build_manual_refusal_offers_forward_to_active_runner(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    claimant_id = f"{tmp_path.name}-claimant"
    await todos_db.add_to_roadmap(_SLUG)
    await todos_db.write_state(
        _SLUG,
        {
            "schema_version": 4,
            "kind": TODO_KIND_CHANGE,
            "phase": "in_progress",
            "lifecycle_phase": LifecyclePhase.PLAN_REVIEW.value,
            "active_runner": claimant_id,
        },
    )
    await _create_runtime_session(
        project_root,
        session_id=claimant_id,
        system_role=ROLE_WORKER,
        working_slug=_SLUG,
        job=JobRole.PLANNER.value,
    )
    session_id = await _create_runtime_session(
        project_root,
        session_id=f"{tmp_path.name}-plain-operator",
        system_role=None,
        working_slug=None,
    )

    with pytest.raises(PermissionError, match=rf"{claimant_id}.*Forward this proposed stamp"):
        await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="plan_ready", caller_session_id=session_id)


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_build_complete_refuses_foreign_worker_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await _add_build_started_todo(todos_db, _SLUG)
    session_id = await _create_runtime_session(
        project_root,
        session_id=f"{tmp_path.name}-foreign-worker",
        system_role=ROLE_WORKER,
        working_slug="other-slug",
        job=JobRole.BUILDER.value,
    )

    with pytest.raises(PermissionError):
        await apply_todo_stamp(
            cwd=str(project_root), slug=_SLUG, stamp_type="build_complete", caller_session_id=session_id
        )

    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["build_gate_claim_at"] == _NO_BUILD_GATE_CLAIM


@pytest.mark.spec(_SPEC, "UC-WSS4")
async def test_post_build_manual_refusal_omits_forward_offer(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    claimant_id = f"{tmp_path.name}-claimant"
    await _add_build_started_todo(todos_db, _SLUG, active_runner=claimant_id)
    await _create_runtime_session(
        project_root,
        session_id=claimant_id,
        system_role=ROLE_WORKER,
        working_slug=_SLUG,
        job=JobRole.BUILDER.value,
    )

    with pytest.raises(PermissionError, match=claimant_id) as exc_info:
        await apply_todo_stamp(cwd=str(project_root), slug=_SLUG, stamp_type="build_complete", caller_session_id=None)

    assert "Forward this proposed stamp" not in str(exc_info.value)
