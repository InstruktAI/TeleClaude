"""Functional tests bound to the workflow state-stamping spec."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from teleclaude.constants import ARTIFACT_TASK_PLAN
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.todo_kind import TODO_KIND_CHANGE, TODO_KIND_TASK

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/state-stamping"
_SLUG = "stamp-target"
_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+")


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
