"""Tests for next-machine slug and holder resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    WorkQueueResolutionReason,
    resolve_next_work_queue_db,
    resolve_runnable_holder_children_db,
    resolve_slug_async,
)
from teleclaude.core.todos_db import TodosDb

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SLUG_LATER_READY = "later-ready"


async def test_prepare_holder_children_are_filtered_by_dependencies(todos_db: TodosDb) -> None:
    """Prepare holder resolution should only return dependency-satisfied children."""
    await todos_db.add_to_roadmap("holder")
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
        mode=HolderResolutionMode.PREPARE,
    )

    assert resolution.children == ("child-a", "child-b")
    assert resolution.runnable == ("child-a",)
    assert resolution.reason is HolderResolutionReason.OK


async def test_work_holder_children_are_filtered_by_dependencies(todos_db: TodosDb) -> None:
    """Work holder resolution should only return dependency-satisfied ready children."""
    await todos_db.add_to_roadmap("holder")
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
        mode=HolderResolutionMode.WORK,
    )

    assert resolution.children == ("child-a", "child-b")
    assert resolution.runnable == ("child-a",)
    assert resolution.reason is HolderResolutionReason.OK


async def test_no_slug_work_queue_skips_unrunnable_holder_and_continues(todos_db: TodosDb) -> None:
    """Automatic work pickup should continue scanning after an unrunnable holder."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.add_to_roadmap(SLUG_LATER_READY)
    await todos_db.write_state(SLUG_LATER_READY, {"schema_version": 3, "lifecycle_phase": "prepared"})

    resolution = await resolve_next_work_queue_db(todos_db, await todos_db.load_deps())

    assert resolution.slug == SLUG_LATER_READY
    assert resolution.holder_slug is None
    assert resolution.child_slugs == ()
    assert resolution.reason is WorkQueueResolutionReason.READY


async def test_holder_with_only_delivered_children_resolves_complete(todos_db: TodosDb) -> None:
    """Delivered children should count toward holder completion, not missing-roadmap state."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.deliver("child-a")

    resolution = await resolve_runnable_holder_children_db(
        todos_db,
        "holder",
        await todos_db.load_deps(),
        mode=HolderResolutionMode.WORK,
    )

    assert resolution.children == ("child-a",)
    assert resolution.runnable == ()
    assert resolution.reason is HolderResolutionReason.COMPLETE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_slug_async_excludes_removed_entries() -> None:
    """Orchestration slug enumeration must exclude soft-removed entries from candidate scanning."""
    mock_db = AsyncMock()
    # list_roadmap returns removed only when explicitly requested
    mock_db.list_roadmap = AsyncMock(return_value=[])
    mock_db.delivered_slugs = AsyncMock(return_value=set())

    slug, is_ready, _desc = await resolve_slug_async(mock_db, slug=None)

    assert slug is None
    assert is_ready is False
    # Verify that list_roadmap was called WITHOUT include_removed=True
    mock_db.list_roadmap.assert_called_once()
    _, kwargs = mock_db.list_roadmap.call_args
    assert kwargs.get("include_removed") is not True
