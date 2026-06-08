"""Functional tests bound to the workflow prepare-state-machine spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from teleclaude.constants import STATE_KEY_DIAGNOSIS, STATE_KEY_IMPLEMENTATION_PLAN
from teleclaude.core.db import Db
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
    is_ready_for_work,
)
from teleclaude.core.next_machine.prepare_step_support import prepare_step_prepared
from teleclaude.core.next_machine.work_steps import _artifact_contract_note
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todos import TodoState

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
