"""Functional tests bound to the workflow prepare-state-machine spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from teleclaude.core.db import Db
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.prepare_step_support import prepare_step_prepared
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/workflow/prepare-state-machine"
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
