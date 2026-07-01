"""Functional tests bound to the workflow dependency-graph spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    deps_satisfied,
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/workflow/dependency-graph"
_PARENT = "parent"
_CHILD = "child"
_HOLDER = "holder"
_CHILD_A = "child-a"
_CHILD_B = "child-b"
_APPROVED_DIGEST = "approved-prd-digest"


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
    kind: str = "change",
    group_slug: str | None = None,
    after: list[str] | None = None,
) -> None:
    await todos_db.add_to_todo(slug, group_slug=group_slug, after=after)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": kind,
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


@pytest.mark.spec(_SPEC, "UC-WDG1")
async def test_prepare_gate_requires_prepared_not_blocked(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    dependencies = {_CHILD: [_PARENT]}

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)

    assert _PARENT not in prepared
    assert not deps_satisfied(dependencies, prepared, _CHILD)

    await todos_db.write_state(
        _PARENT,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.BLOCKED.value,
        },
    )

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)

    assert _PARENT not in prepared
    assert not deps_satisfied(dependencies, prepared, _CHILD)


@pytest.mark.spec(_SPEC, "UC-WDG2")
async def test_prepared_clears_prepare_gate_but_not_work_gate(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    dependencies = {_CHILD: [_PARENT]}

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered = await effective_delivered_slugs_for_dependencies(todos_db)

    assert _PARENT in prepared
    assert deps_satisfied(dependencies, prepared, _CHILD)
    assert _PARENT not in delivered
    assert not deps_satisfied(dependencies, delivered, _CHILD)

    resolution = await resolve_runnable_holder_children_db(
        todos_db,
        _PARENT,
        await todos_db.load_deps(),
        mode=HolderResolutionMode.WORK,
    )

    assert resolution.reason is HolderResolutionReason.NOT_HOLDER


@pytest.mark.spec(_SPEC, "UC-WDG2")
async def test_prd_approval_clears_prepare_gate_but_not_work_gate(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    parent_state = await todos_db.read_state(_PARENT)
    assert parent_state is not None
    parent_state["approvals"] = {
        "prd_approved": {
            "approved": True,
            "approved_digest": _APPROVED_DIGEST,
        }
    }
    await todos_db.write_state(_PARENT, parent_state)
    dependencies = {_CHILD: [_PARENT]}

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered = await effective_delivered_slugs_for_dependencies(todos_db)

    assert _PARENT in prepared
    assert deps_satisfied(dependencies, prepared, _CHILD)
    assert _PARENT not in delivered
    assert not deps_satisfied(dependencies, delivered, _CHILD)


@pytest.mark.spec(_SPEC, "UC-WDG6")
async def test_task_parent_clears_prepare_gate_only_on_delivery(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED, kind="task")
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    dependencies = {_CHILD: [_PARENT]}

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered = await effective_delivered_slugs_for_dependencies(todos_db)

    assert _PARENT not in prepared
    assert not deps_satisfied(dependencies, prepared, _CHILD)
    assert _PARENT not in delivered

    await todos_db.deliver(_PARENT)

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)
    delivered = await effective_delivered_slugs_for_dependencies(todos_db)

    assert _PARENT in delivered
    assert deps_satisfied(dependencies, delivered, _CHILD)
    assert deps_satisfied(dependencies, prepared, _CHILD)


@pytest.mark.spec(_SPEC, "UC-WDG2")
async def test_holder_dependency_rolls_up_when_all_children_are_prepared(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await todos_db.add_to_todo(_HOLDER)
    await _add_todo(todos_db, _CHILD_A, lifecycle_phase=LifecyclePhase.PREPARED, group_slug=_HOLDER)
    await _add_todo(todos_db, _CHILD_B, lifecycle_phase=LifecyclePhase.BUILD_STARTED, group_slug=_HOLDER)

    prepared = await effective_prepared_slugs_for_dependencies(todos_db)

    assert {_HOLDER, _CHILD_A, _CHILD_B}.issubset(prepared)


@pytest.mark.spec(_SPEC, "UC-WDG1")
async def test_holder_prepare_resolution_uses_prepared_gate(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await todos_db.add_to_todo(_HOLDER)
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING)
    await _add_todo(
        todos_db,
        _CHILD,
        lifecycle_phase=LifecyclePhase.DRAFT,
        group_slug=_HOLDER,
        after=[_PARENT],
    )

    blocked = await resolve_runnable_holder_children_db(
        todos_db,
        _HOLDER,
        await todos_db.load_deps(),
        mode=HolderResolutionMode.PREPARE,
    )

    assert blocked.reason is HolderResolutionReason.DEPS_UNSATISFIED
    assert blocked.runnable == ()

    await todos_db.write_state(
        _PARENT,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PREPARED.value,
        },
    )

    runnable = await resolve_runnable_holder_children_db(
        todos_db,
        _HOLDER,
        await todos_db.load_deps(),
        mode=HolderResolutionMode.PREPARE,
    )

    assert runnable.reason is HolderResolutionReason.OK
    assert runnable.runnable == (_CHILD,)
