"""Tests for next-machine slug and holder resolution."""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.slug_resolution import (
    resolve_next_work_queue_db,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.todos_db import TodosDb

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

REASON_COMPLETE = "complete"
REASON_OK = "ok"
REASON_READY = "ready"
SLUG_LATER_READY = "later-ready"


async def test_prepare_holder_children_are_filtered_by_dependencies(todos_db: TodosDb) -> None:
    """Prepare holder resolution should only return dependency-satisfied children."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.write_state(
        "holder",
        {
            "schema_version": 3,
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": ["child-a", "child-b"]},
        },
    )
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.add_to_roadmap("child-b", group_slug="holder")
    await todos_db.write_state("child-b", {"schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.add_to_roadmap("dependency")
    await todos_db.set_deps("child-b", after=["dependency"])

    resolution = await resolve_runnable_holder_children_db(
        todos_db,
        "holder",
        await todos_db.load_deps(),
        mode="prepare",
    )

    assert resolution.children == ("child-a", "child-b")
    assert resolution.runnable == ("child-a",)
    assert resolution.reason == REASON_OK


async def test_work_holder_children_are_filtered_by_dependencies(todos_db: TodosDb) -> None:
    """Work holder resolution should only return dependency-satisfied ready children."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.write_state(
        "holder",
        {
            "schema_version": 3,
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": ["child-a", "child-b"]},
        },
    )
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.add_to_roadmap("child-b", group_slug="holder")
    await todos_db.write_state("child-b", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.add_to_roadmap("dependency")
    await todos_db.set_deps("child-b", after=["dependency"])

    resolution = await resolve_runnable_holder_children_db(
        todos_db,
        "holder",
        await todos_db.load_deps(),
        mode="work",
    )

    assert resolution.children == ("child-a", "child-b")
    assert resolution.runnable == ("child-a",)
    assert resolution.reason == REASON_OK


async def test_no_slug_work_queue_skips_unrunnable_holder_and_continues(todos_db: TodosDb) -> None:
    """Automatic work pickup should continue scanning after an unrunnable holder."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.write_state(
        "holder",
        {
            "schema_version": 3,
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": ["child-a"]},
        },
    )
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.add_to_roadmap(SLUG_LATER_READY)
    await todos_db.write_state(SLUG_LATER_READY, {"schema_version": 3, "lifecycle_phase": "prepared"})

    resolution = await resolve_next_work_queue_db(todos_db, await todos_db.load_deps())

    assert resolution.slug == SLUG_LATER_READY
    assert resolution.holder_slug is None
    assert resolution.child_slugs == ()
    assert resolution.reason == REASON_READY


async def test_holder_with_only_delivered_children_resolves_complete(todos_db: TodosDb) -> None:
    """Delivered children should count toward holder completion, not missing-roadmap state."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.write_state(
        "holder",
        {
            "schema_version": 3,
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": ["child-a"]},
        },
    )
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.deliver("child-a")

    resolution = await resolve_runnable_holder_children_db(
        todos_db,
        "holder",
        await todos_db.load_deps(),
        mode="work",
    )

    assert resolution.children == ("child-a",)
    assert resolution.runnable == ()
    assert resolution.reason == REASON_COMPLETE
