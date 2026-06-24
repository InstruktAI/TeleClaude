"""Functional tests bound to the workflow work-state-machine spec."""

from __future__ import annotations

import shutil
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException

from teleclaude.api import todo_artifact_authority
from teleclaude.api.auth import CallerIdentity
from teleclaude.constants import ARTIFACT_IMPLEMENTATION_PLAN, JobRole
from teleclaude.core.db import Db
from teleclaude.core.next_machine import work as work_machine
from teleclaude.core.next_machine import work_steps
from teleclaude.core.next_machine._types import WorkPhase
from teleclaude.core.next_machine.git_ops import ArtifactDriftStatus
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.paths import COMMANDS_DIR
from teleclaude.types.todos import TodoState


def _sanitize(output: str, project_root: Path) -> str:
    """Strip volatile per-run paths so dispatch snapshots stay deterministic."""
    return output.replace(str(project_root), "/repo").replace(str(COMMANDS_DIR), "<commands>")


pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/work-state-machine"
_SLUG = "prepared-work"
_FINALIZED_SLUG = "finalized-work"
_UNKNOWN_SLUG = "unknown-work"
_PLAN_BODY = "# Plan"
_RUNNER_SESSION = "orchestrator-session"


@dataclass(frozen=True)
class _Session:
    session_id: str
    title: str
    subdir: str | None = None
    lifecycle_status: str | None = None
    closed_at: datetime | None = None
    last_activity: datetime | None = None
    last_message_sent_at: datetime | None = None
    last_agent_stop_at: datetime | None = None


class _CapturingDb:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = sessions

    async def list_sessions(
        self,
        *,
        include_closed: bool = False,
        initiator_session_id: str | None = None,
    ) -> list[_Session]:
        _ = include_closed, initiator_session_id
        return self._sessions


@dataclass
class _FakeSession:
    session_id: str
    job: str | None


class _SessionStoreDb:
    """Capturing db that also serves session role reads and records job mutations.

    The promotion helper reads the caller's job via ``get_session`` and mutates it
    via ``update_session``; this fake records every mutation so a test can assert
    that exactly one in-place job change happened (and no second session spawned).
    """

    def __init__(self, sessions: dict[str, _FakeSession]) -> None:
        self._sessions = sessions
        self.updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - dynamic update payload

    async def list_sessions(
        self,
        *,
        include_closed: bool = False,
        initiator_session_id: str | None = None,
    ) -> list[_Session]:
        _ = include_closed, initiator_session_id
        return []

    async def get_session(self, session_id: str) -> _FakeSession | None:
        return self._sessions.get(session_id)

    async def update_session(self, session_id: str, **fields: object) -> _FakeSession | None:
        self.updates.append((session_id, fields))
        session = self._sessions.get(session_id)
        job = fields.get("job")
        if session is not None and isinstance(job, str):
            session.job = job
        return session


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _seed_prepared_with_runner(project_root: Path, *, active_runner: str) -> TodosDb:
    """Seed a PREPARED todo whose slug claim is held by ``active_runner``."""
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG)
    await todos_db.write_state(
        _SLUG,
        TodoState(
            kind="change",
            phase="in_progress",
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            schema_version=5,
            active_runner=active_runner,
        ).model_dump(exclude_none=True),
    )
    return todos_db


def _patch_work_entry_drift(
    monkeypatch: pytest.MonkeyPatch,
    *,
    drift_classes: dict[str, ArtifactDriftStatus],
) -> None:
    """Drive a deterministic work-entry drift derivation for the single plan artifact."""

    async def _derive(*_args: object, **_kwargs: object) -> dict[str, dict[str, ArtifactDriftStatus]]:
        return {ARTIFACT_IMPLEMENTATION_PLAN: drift_classes}

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "derive_lifecycle_drift", _derive)


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _no_work_entry_drift(
    _db: Db, _todos_db: TodosDb, _resolved_slug: str, _cwd: str, _phase_slug: str
) -> str | None:
    return None


async def _run_merge_main_failure_with_live_builder(
    *,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle_phase: LifecyclePhase,
) -> str:
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG)
    await todos_db.write_state(
        _SLUG,
        TodoState(
            kind="change",
            lifecycle_phase=lifecycle_phase.value,
            schema_version=5,
        ).model_dump(exclude_none=True),
    )
    worktree_cwd = project_root / "trees" / _SLUG
    worktree_cwd.mkdir(parents=True)

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "conflict details")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")

    return await next_work(
        cast(
            Db,
            _CapturingDb(
                [
                    _Session(
                        "builder-session",
                        f"/next-build {_SLUG}",
                        subdir=f"trees/{_SLUG}",
                    )
                ]
            ),
        ),
        _SLUG,
        str(project_root),
    )


async def _run_build_complete_review_dispatch(
    *,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    sessions: list[_Session],
    round_num: int,
    baseline_commit: str = "",
) -> str:
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG)
    model = TodoState(
        kind="change",
        lifecycle_phase=LifecyclePhase.BUILD_COMPLETE.value,
        schema_version=5,
    )
    model.build_review.round = round_num
    model.build_review.baseline_commit = baseline_commit
    await todos_db.write_state(_SLUG, model.model_dump(exclude_none=True))
    worktree_cwd = project_root / "trees" / _SLUG
    worktree_cwd.mkdir(parents=True)

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    async def _guidance(_db: Db) -> str:
        return "agent guidance"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_steps, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_steps, "compose_agent_guidance", _guidance)

    output = await next_work(cast(Db, _CapturingDb(sessions)), _SLUG, str(project_root))
    return output.replace(str(project_root), "/repo")


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_prepared_entry_advances_to_build_started_without_removed_phase_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG)
    await todos_db.write_state(
        _SLUG,
        TodoState(
            kind="change",
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            schema_version=5,
        ).model_dump(exclude_none=True),
    )
    worktree_cwd = project_root / "trees" / _SLUG
    worktree_cwd.mkdir(parents=True)
    dispatch_phases: list[WorkPhase] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    async def _dispatch_build_started(**kwargs: object) -> tuple[bool, str]:
        phase = kwargs["phase"]
        assert isinstance(phase, WorkPhase)
        dispatch_phases.append(phase)
        state = await todos_db.read_state(_SLUG)
        assert state is not None
        assert state["lifecycle_phase"] == LifecyclePhase.BUILD_STARTED.value
        return False, "BUILD_START_DISPATCH: prepared-work"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch_build_started)

    output = await next_work(cast(Db, _CapturingDb([])), _SLUG, str(project_root))

    assert dispatch_phases == [WorkPhase.BUILD_STARTED]
    assert output == snapshot


async def test_build_complete_reuses_live_reviewer_for_incremental_rereview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_build_complete_review_dispatch(
        project_root=project_root,
        monkeypatch=monkeypatch,
        sessions=[
            _Session(
                "reviewer-session",
                f"/next-review-build {_SLUG}",
                subdir=f"trees/{_SLUG}",
                lifecycle_status="closed",
                closed_at=datetime(2026, 6, 21, tzinfo=UTC),
            )
        ],
        round_num=1,
        baseline_commit="baseline-sha",
    )

    assert output == snapshot


async def test_build_complete_spawns_reviewer_without_live_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_build_complete_review_dispatch(
        project_root=project_root,
        monkeypatch=monkeypatch,
        sessions=[],
        round_num=0,
    )

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_merge_main_failure_routes_recovery_to_live_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_merge_main_failure_with_live_builder(
        project_root=project_root,
        monkeypatch=monkeypatch,
        lifecycle_phase=LifecyclePhase.BUILD_STARTED,
    )

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_merge_main_failure_after_build_complete_routes_recovery_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    output = await _run_merge_main_failure_with_live_builder(
        project_root=project_root,
        monkeypatch=monkeypatch,
        lifecycle_phase=LifecyclePhase.BUILD_COMPLETE,
    )

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_finalize_ready_terminal_output_ends_slug_workers_and_self(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_FINALIZED_SLUG)
    await todos_db.write_state(
        _FINALIZED_SLUG,
        TodoState(
            kind="change",
            phase="in_progress",
            lifecycle_phase=LifecyclePhase.FINALIZE_READY.value,
            schema_version=5,
        ).model_dump(exclude_none=True),
    )
    worktree_cwd = project_root / "trees" / _FINALIZED_SLUG
    worktree_cwd.mkdir(parents=True)

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_steps, "get_session_id", lambda: "orchestrator-session")

    output = await next_work(
        cast(
            Db,
            _CapturingDb(
                [
                    _Session(
                        "builder-session",
                        f"/next-build {_FINALIZED_SLUG}",
                        subdir=f"trees/{_FINALIZED_SLUG}",
                    ),
                    _Session(
                        "reviewer-session",
                        f"/next-review-build {_FINALIZED_SLUG}",
                        subdir=f"trees/{_FINALIZED_SLUG}",
                    ),
                    _Session(
                        "finalizer-session",
                        f"/next-finalize {_FINALIZED_SLUG}",
                        subdir=f"trees/{_FINALIZED_SLUG}",
                    ),
                ]
            ),
        ),
        _FINALIZED_SLUG,
        str(project_root),
    )

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_kickback_releases_worktree_and_emits_terminal_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_SLUG)
    await todos_db.write_state(
        _SLUG,
        TodoState(
            kind="change",
            phase="in_progress",
            lifecycle_phase=LifecyclePhase.BUILD_STARTED.value,
            schema_version=5,
            active_runner="orchestrator-session",
        ).model_dump(exclude_none=True),
    )
    # A kickback marks the plan-review cleared-by-substantive-drift; reproduce that signal.
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    writer = StateWriter(state)
    writer.state.plan_review.cleared_by_substantive_drift = True
    await writer.commit(todos_db, _SLUG)
    await todos_db.write_artifact(_SLUG, ARTIFACT_IMPLEMENTATION_PLAN, _PLAN_BODY, updated_by="test")

    worktree_cwd = project_root / "trees" / _SLUG
    worktree_cwd.mkdir(parents=True)

    released: list[tuple[str, str]] = []

    def _release(cwd: str, slug: str, **_kwargs: object) -> None:
        released.append((cwd, slug))
        shutil.rmtree(worktree_cwd)

    dispatched: list[str] = []

    async def _dispatch(**_kwargs: object) -> tuple[bool, str]:
        dispatched.append("dispatched")
        return False, "should-not-run"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "cleanup_delivered_slug", _release)
    monkeypatch.setattr(work_machine, "get_session_id", lambda: "orchestrator-session")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch)

    output = await next_work(
        cast(Db, _CapturingDb([_Session("builder-session", f"/next-build {_SLUG}", subdir=f"trees/{_SLUG}")])),
        _SLUG,
        str(project_root),
    )

    # The emitted terminal script (end the slug's worker, end self, do not re-enter work) is the contract.
    assert output == snapshot
    assert released == [(str(project_root), _SLUG)]
    assert not worktree_cwd.exists()
    assert dispatched == []
    # The durable todo and its artifacts survive the working-resource release.
    assert await todos_db.read_artifact(_SLUG, ARTIFACT_IMPLEMENTATION_PLAN) == _PLAN_BODY


@pytest.mark.spec(_SPEC, "UC-WSM3")
async def test_work_without_slug_terminalizes_without_selecting_followup_work(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await _project_db(project_root)

    output = await next_work(cast(Db, _CapturingDb([])), None, str(project_root))

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM2")
async def test_work_unknown_slug_does_not_create_todo_row(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)

    output = await next_work(cast(Db, _CapturingDb([])), _UNKNOWN_SLUG, str(project_root))

    assert not await todos_db.slug_in_todo(_UNKNOWN_SLUG)


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_work_entry_pending_drift_dispatches_analyzer_and_reenters_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await _seed_prepared_with_runner(project_root, active_runner="orchestrator-session")
    _patch_work_entry_drift(monkeypatch, drift_classes={"owned-snippet": "pending"})

    async def _guidance(_db: Db) -> str:
        return "agent guidance"

    monkeypatch.setattr(work_machine, "compose_agent_guidance", _guidance)

    ensure_called: list[str] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        ensure_called.append(_slug)
        return "", None

    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)

    output = await next_work(cast(Db, _CapturingDb([])), _SLUG, str(project_root))

    # Pending drift dispatches the analyzer and re-enters work — no worktree created.
    # The emitted analyzer-dispatch script (next-drift-analyze + telec todo work re-entry,
    # never telec todo prepare) is verified by the snapshot.
    assert ensure_called == []
    assert _sanitize(output, project_root) == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM5")
async def test_work_entry_substantive_drift_promotes_claim_holder_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _seed_prepared_with_runner(project_root, active_runner="orchestrator-session")
    _patch_work_entry_drift(monkeypatch, drift_classes={"owned-snippet": "substantive"})
    monkeypatch.setattr(work_machine, "get_session_id", lambda: "orchestrator-session")

    db = _SessionStoreDb(
        {"orchestrator-session": _FakeSession("orchestrator-session", JobRole.WORK_ORCHESTRATOR.value)}
    )
    # The prepare write-authority guard reads the live session job from the same store.
    monkeypatch.setattr(todo_artifact_authority, "runtime_db", db)
    identity = CallerIdentity(
        session_id="orchestrator-session", system_role=None, human_role=None, tmux_session_name=None
    )

    ensure_called: list[str] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        ensure_called.append(_slug)
        return "", None

    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)

    # Before the bounce the claim-holder is a work-orchestrator: the write guard refuses (403).
    with pytest.raises(HTTPException) as before:
        await todo_artifact_authority.refuse_non_prepare_writer(identity, _SLUG, ARTIFACT_IMPLEMENTATION_PLAN)
    assert before.value.status_code == 403

    output = await next_work(cast(Db, db), _SLUG, str(project_root))

    # SC-2: the same session is promoted in place to prepare-orchestrator, and the write
    # guard now ADMITS its re-derivation write — no 403 — because it carries prepare authority.
    assert db.updates == [("orchestrator-session", {"job": JobRole.PREPARE_ORCHESTRATOR.value})]
    await todo_artifact_authority.refuse_non_prepare_writer(identity, _SLUG, ARTIFACT_IMPLEMENTATION_PLAN)
    # SC-1: no second driver — the held claim is unchanged and no extra session was created,
    # so the spawn path that would raise a 409 is never taken; no worktree on the bounce.
    state = await todos_db.read_state(_SLUG)
    assert state is not None
    assert state["active_runner"] == _RUNNER_SESSION
    assert list(db._sessions) == [_RUNNER_SESSION]
    assert ensure_called == []
    assert _sanitize(output, project_root) == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM5")
async def test_work_entry_substantive_drift_refuses_non_claim_holder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await _seed_prepared_with_runner(project_root, active_runner="other-session")
    _patch_work_entry_drift(monkeypatch, drift_classes={"owned-snippet": "substantive"})
    monkeypatch.setattr(work_machine, "get_session_id", lambda: "orchestrator-session")

    db = _SessionStoreDb(
        {"orchestrator-session": _FakeSession("orchestrator-session", JobRole.WORK_ORCHESTRATOR.value)}
    )

    output = await next_work(cast(Db, db), _SLUG, str(project_root))

    # A caller that is not the live active_runner is not promoted.
    assert db.updates == []
    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM5")
async def test_work_entry_substantive_drift_refuses_non_work_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await _seed_prepared_with_runner(project_root, active_runner="orchestrator-session")
    _patch_work_entry_drift(monkeypatch, drift_classes={"owned-snippet": "substantive"})
    monkeypatch.setattr(work_machine, "get_session_id", lambda: "orchestrator-session")

    db = _SessionStoreDb(
        {"orchestrator-session": _FakeSession("orchestrator-session", JobRole.PREPARE_ORCHESTRATOR.value)}
    )

    output = await next_work(cast(Db, db), _SLUG, str(project_root))

    # A caller whose job is not work-orchestrator is not promoted.
    assert db.updates == []
    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WSM0")
async def test_work_entry_cosmetic_drift_proceeds_to_build_without_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    await _seed_prepared_with_runner(project_root, active_runner="orchestrator-session")
    _patch_work_entry_drift(monkeypatch, drift_classes={"owned-snippet": "cosmetic"})

    worktree_cwd = project_root / "trees" / _SLUG
    worktree_cwd.mkdir(parents=True)
    dispatch_phases: list[WorkPhase] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    async def _dispatch_build_started(**kwargs: object) -> tuple[bool, str]:
        phase = kwargs["phase"]
        assert isinstance(phase, WorkPhase)
        dispatch_phases.append(phase)
        return False, "BUILD_START_DISPATCH: prepared-work"

    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch_build_started)

    db = _SessionStoreDb(
        {"orchestrator-session": _FakeSession("orchestrator-session", JobRole.WORK_ORCHESTRATOR.value)}
    )

    output = await next_work(cast(Db, db), _SLUG, str(project_root))

    # SC-3: cosmetic drift proceeds to build with no role change.
    assert dispatch_phases == [WorkPhase.BUILD_STARTED]
    assert db.updates == []
    assert output == snapshot
