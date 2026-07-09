"""Functional tests bound to the workflow domain spec's slug-resolution scenario."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine import work as work_machine
from teleclaude.core.next_machine._types import ItemPhase, WorkPhase
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/domain/workflow"
_SLUG = "reused-slug"


class _CapturingDb:
    async def list_sessions(
        self,
        *,
        include_closed: bool = False,
        initiator_session_id: str | None = None,
    ) -> list[object]:
        _ = include_closed, initiator_session_id
        return []


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _no_work_entry_drift(
    _db: Db, _todos_db: TodosDb, _resolved_slug: str, _cwd: str, _phase_slug: str
) -> str | None:
    return None


@pytest.mark.spec(_SPEC, "UC-WFL-29")
async def test_delivered_and_live_same_slug_resolves_work_to_the_live_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delivered historical row must never block work on a reused-slug live row."""
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)

    # First lifecycle for the slug: seed state and deliver — a terminal historical row.
    await todos_db.add_to_todo(_SLUG, lineage="human:test@example.com")
    await todos_db.write_state(
        _SLUG,
        TodoState(kind="change", lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=5).model_dump(
            exclude_none=True
        ),
    )
    await todos_db.deliver(_SLUG)

    # Second lifecycle reuses the same slug: a new, distinct, live active row.
    await todos_db.add_to_todo(_SLUG, lineage="human:test@example.com")
    await todos_db.write_state(
        _SLUG,
        TodoState(kind="change", lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=5).model_dump(
            exclude_none=True
        ),
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
        return False, f"BUILD_START_DISPATCH: {_SLUG}"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_check_work_entry_drift", _no_work_entry_drift)
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch_build_started)

    await next_work(cast(Db, _CapturingDb()), _SLUG, str(project_root))

    assert dispatch_phases == [WorkPhase.BUILD_STARTED]

    state_after = await todos_db.read_state(_SLUG)
    assert state_after is not None
    assert state_after["phase"] == ItemPhase.IN_PROGRESS.value
