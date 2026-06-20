"""Functional tests bound to the workflow work-state-machine spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import work as work_machine
from teleclaude.core.next_machine import work_steps
from teleclaude.core.next_machine._types import WorkPhase
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/work-state-machine"
_SLUG = "prepared-work"
_FINALIZED_SLUG = "finalized-work"
_UNKNOWN_SLUG = "unknown-work"


@dataclass(frozen=True)
class _Session:
    session_id: str
    title: str
    subdir: str | None = None


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


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _no_work_entry_drift(_todos_db: TodosDb, _resolved_slug: str, _cwd: str, _phase_slug: str) -> str | None:
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
            schema_version=4,
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
            schema_version=4,
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
            schema_version=4,
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
    assert output == snapshot
