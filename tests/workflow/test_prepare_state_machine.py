"""Functional tests bound to the workflow prepare-state-machine spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine import work as work_machine
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.git_ops import DRIFT_FRESH, derive_artifact_drift
from teleclaude.core.next_machine.kinds import (
    BUG_DIAGNOSE_KINDS,
    FAST_TRACK_PREPARED_KINDS,
    KIND_BUG,
    KIND_TASK,
)
from teleclaude.core.next_machine.lifecycle import (
    LIFECYCLE_PHASE_ORDER,
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    collapse_drift,
    derive_lifecycle_drift,
    is_ready_for_work,
)
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.prepare_step_support import prepare_step_prepared
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.next_machine.work_steps import _artifact_contract_note
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todos import DependencyEntry, DriftReviewedStamp, RoadmapStatusLiteral, TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/prepare-state-machine"
_WORK_SPEC = "project/spec/feature/workflow/work-state-machine"
_PROJECT_ROOT = "/repo"
_PARENT = "parent"
_CHILD = "child"
_PARENT_WORKER = "sess-parent-worker"
_PARENT_REVIEWER = "sess-parent-reviewer"
_UNRELATED = "sess-unrelated"
_PREFIX_COLLISION = "sess-prefix-collision"
_WORKTREE_SESSION = "sess-worktree"
_DRIFT_SPEC = "project/spec/feature/workflow/drift-detection"
_DRIFT_SLUG = "matching-drift-bug"
_INPUT_DIGEST = "input-v1"
_DIAGNOSIS_DIGEST = "diagnosis-v1"


@dataclass(frozen=True)
class _Session:
    session_id: str
    title: str
    subdir: str | None = None


class _CapturingDb:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = sessions

    async def list_sessions(self, *, include_closed: bool = False) -> list[_Session]:
        _ = include_closed
        return self._sessions


class _DependencyReader:
    def __init__(self, deps: list[DependencyEntry]) -> None:
        self._deps = deps

    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return self._deps


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
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


def _dependency_entry(dep_slug: str, roadmap_status: RoadmapStatusLiteral) -> DependencyEntry:
    return DependencyEntry(dep_slug=dep_slug, roadmap_status=roadmap_status)


@pytest.mark.spec(_SPEC, "UC-WPS1")
async def test_prepared_auto_continue_reuses_parent_prepare_worker(tmp_path: Path, snapshot: object) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
            _Session(_UNRELATED, "/next-prepare unrelated"),
            _Session(_PREFIX_COLLISION, f"/next-prepare {_PARENT}-extra"),
            _Session(_WORKTREE_SESSION, f"/next-prepare {_PARENT}", subdir=f"trees/{_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WPS1")
async def test_prepared_auto_continue_spawns_fresh_when_parent_worker_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])

    async def _missing_prepare_worker(_db: Db, _slug: str, _command_value: str) -> str | None:
        return None

    monkeypatch.setattr(
        "teleclaude.core.next_machine.prepare_step_support.find_live_prepare_worker_for_slug",
        _missing_prepare_worker,
    )
    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert output == snapshot


def _bug_model() -> TodoState:
    return TodoState(kind=KIND_BUG, schema_version=4)


def _prepared_bug_model() -> TodoState:
    model = TodoState(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=4)
    model.plan_review.verdict = "approve"
    model.artifacts.input.digest = _INPUT_DIGEST
    model.artifacts.input.async_provenance_complete = True
    model.artifacts.diagnosis.digest = _DIAGNOSIS_DIGEST
    model.artifacts.diagnosis.upstream_digests = {STATE_KEY_INPUT: _INPUT_DIGEST}
    model.artifacts.diagnosis.async_provenance_complete = True
    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.upstream_digests = {
        STATE_KEY_PRD: "",
        STATE_KEY_ARCHITECTURE: "",
        STATE_KEY_DIAGNOSIS: _DIAGNOSIS_DIGEST,
    }
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict="cosmetic",
        upstream_digests_at_review={
            STATE_KEY_PRD: "",
            STATE_KEY_ARCHITECTURE: "",
            STATE_KEY_DIAGNOSIS: _DIAGNOSIS_DIGEST,
        },
    )
    return model


def test_bug_kind_routes_through_diagnose_not_fast_track() -> None:
    assert KIND_BUG in BUG_DIAGNOSE_KINDS
    assert KIND_BUG not in FAST_TRACK_PREPARED_KINDS
    assert KIND_TASK in FAST_TRACK_PREPARED_KINDS
    arch_review = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.ARCHITECTURE_REVIEW)
    diagnose = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.DIAGNOSE)
    plan_drafting = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.PLAN_DRAFTING)
    assert arch_review < diagnose < plan_drafting


def test_bug_derives_diagnose_until_diagnosis_then_flows_like_a_plan() -> None:
    model = _bug_model()
    assert adopt_prepare_handoff_phase(model, artifact_presence={}) == LifecyclePhase.DIAGNOSE

    with_diagnosis = {STATE_KEY_DIAGNOSIS: True}
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_diagnosis) == LifecyclePhase.PLAN_DRAFTING

    with_plan = {STATE_KEY_DIAGNOSIS: True, STATE_KEY_IMPLEMENTATION_PLAN: True}
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_plan) == LifecyclePhase.PLAN_REVIEW

    model.plan_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_plan) == LifecyclePhase.PREPARED


def test_bug_is_not_work_ready_before_prepared() -> None:
    diagnose_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.DIAGNOSE.value)
    plan_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value)
    prepared_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PREPARED.value)
    assert diagnose_ready is False
    assert plan_ready is False
    assert prepared_ready is True


@pytest.mark.spec(_WORK_SPEC, "UC-WSM1")
def test_bug_work_mandate_names_plan_and_diagnosis(snapshot: object) -> None:
    assert _artifact_contract_note("my-bug", KIND_BUG) == snapshot


@pytest.mark.spec(_SPEC, "UC-WPS2")
async def test_prepared_cleanup_is_unchanged_without_unblocked_children(tmp_path: Path, snapshot: object) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert output == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD3")
async def test_prepared_bug_with_matching_diagnosis_upstream_does_not_redispatch_drift_analyzer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_roadmap(_DRIFT_SLUG)
    state = _prepared_bug_model().model_dump(exclude_none=True)
    await todos_db.write_state(_DRIFT_SLUG, state)
    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", _test_guidance)
    db = _CapturingDb([])

    _, output = await _prepare_dispatch(
        db=cast(Db, db),
        todos_db=todos_db,
        slug=_DRIFT_SLUG,
        cwd=str(project_root),
        phase=PreparePhase.PREPARED,
        state=state,
    )

    assert output == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD9")
async def test_prepare_hydration_refreshes_stale_referenced_paths_without_stamp_churn(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "stale-reference-refresh"
    await todos_db.add_to_roadmap(slug)
    await todos_db.write_artifact(
        slug,
        ARTIFACT_IMPLEMENTATION_PLAN,
        "Grounding mentions manifests/cli-surface.md, but no contract block declares it.",
    )
    model = _prepared_bug_model()
    entry = model.artifacts.implementation_plan
    entry.produced_at = "2026-06-10T00:00:00+00:00"
    entry.codebase_sha_at_write = "write-sha"
    entry.referenced_paths = [
        "manifests/cli-surface.md",
        "teleclaude/core/next_machine/git_ops.py",
    ]
    entry.dependency_set_at_write = [_dependency_entry("dep", "active")]
    produced_at_before = entry.produced_at
    state = model.model_dump(exclude_none=True)
    await todos_db.write_state(slug, state)
    stamp_before = model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN].model_copy(deep=True)

    await next_prepare(cast(Db, _CapturingDb([])), slug, str(project_root))

    persisted = await todos_db.read_state(slug)
    assert persisted is not None
    writer = StateWriter(persisted)
    refreshed = writer.state.artifacts.implementation_plan
    assert refreshed.referenced_paths == []
    assert refreshed.async_provenance_complete is True
    assert refreshed.dependency_set_at_write == [_dependency_entry("dep", "active")]
    assert refreshed.produced_at == produced_at_before
    assert writer.state.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] == stamp_before
    assert derive_artifact_drift(refreshed, None, "", "") == DRIFT_FRESH

    drift = await derive_lifecycle_drift(
        slug,
        writer.state,
        repo_root=str(project_root),
        todos_db=_DependencyReader([_dependency_entry("dep", "delivered")]),
        snippet_digest_fn=lambda _snippet_id: "",
        writer=writer,
    )
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] == DRIFT_FRESH


async def test_prepare_hydration_refreshes_declared_referenced_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "declared-reference-refresh"
    await todos_db.add_to_roadmap(slug)
    await todos_db.write_artifact(
        slug,
        ARTIFACT_IMPLEMENTATION_PLAN,
        """
```referenced-paths
teleclaude/core/next_machine/git_ops.py
tests/workflow/test_prepare_state_machine.py
```
""",
    )
    model = _prepared_bug_model()
    model.artifacts.implementation_plan.produced_at = "2026-06-10T00:00:00+00:00"
    model.artifacts.implementation_plan.referenced_paths = ["manifests/cli-surface.md"]
    produced_at_before = model.artifacts.implementation_plan.produced_at
    await todos_db.write_state(slug, model.model_dump(exclude_none=True))
    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", _test_guidance)

    await next_prepare(cast(Db, _CapturingDb([])), slug, str(project_root))

    persisted = await todos_db.read_state(slug)
    assert persisted is not None
    writer = StateWriter(persisted)
    assert writer.state.artifacts.implementation_plan.referenced_paths == [
        "teleclaude/core/next_machine/git_ops.py",
        "tests/workflow/test_prepare_state_machine.py",
    ]
    assert writer.state.artifacts.implementation_plan.produced_at == produced_at_before


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD6")
async def test_work_entry_with_matching_diagnosis_upstream_dispatches_build_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_roadmap(_DRIFT_SLUG)
    await todos_db.write_state(_DRIFT_SLUG, _prepared_bug_model().model_dump(exclude_none=True))
    worktree_cwd = project_root / "trees" / _DRIFT_SLUG
    worktree_cwd.mkdir(parents=True)
    dispatch_phases: list[WorkPhase] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    async def _dispatch_build_started(**kwargs: object) -> tuple[bool, str]:
        phase = kwargs["phase"]
        assert isinstance(phase, WorkPhase)
        dispatch_phases.append(phase)
        return False, "BUILD_START_DISPATCH: matching-drift-bug"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch_build_started)

    output = await next_work(cast(Db, _CapturingDb([])), _DRIFT_SLUG, str(project_root))

    assert dispatch_phases == [WorkPhase.BUILD_STARTED]
    assert output == snapshot


async def _test_guidance(_db: Db) -> str:
    return "agent guidance"
