"""Tests for TodosDbStateMixin — todo state persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


async def test_read_state_returns_none_for_unknown_slug(todos_db: TodosDb) -> None:
    result = await todos_db.read_state("nonexistent")
    assert result is None


async def test_write_then_read_state_round_trips(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    state = {"schema_version": 2, "current": "input_assessment", "phase": "pending"}
    await todos_db.write_state("my-slug", state)
    result = await todos_db.read_state("my-slug")
    assert result is not None
    assert result["current"] == "input_assessment"
    assert result["schema_version"] == 2


async def test_write_state_updates_existing_row(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    state_v1 = {"schema_version": 2, "current": "input_assessment"}
    await todos_db.write_state("my-slug", state_v1)

    state_v2 = {"schema_version": 2, "current": "prepared"}
    await todos_db.write_state("my-slug", state_v2)

    result = await todos_db.read_state("my-slug")
    assert result is not None
    assert result["current"] == "prepared"


async def test_delete_state_removes_row(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "pending"})
    await todos_db.delete_state("my-slug")
    assert await todos_db.read_state("my-slug") is None


async def test_list_slugs_returns_all_stored(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("alpha")
    await todos_db.add_to_roadmap("beta")
    await todos_db.write_state("alpha", {"current": "pending"})
    await todos_db.write_state("beta", {"current": "prepared"})
    slugs = await todos_db.list_slugs()
    assert set(slugs) == {"alpha", "beta"}


async def test_list_slugs_empty_when_no_state(todos_db: TodosDb) -> None:
    slugs = await todos_db.list_slugs()
    assert slugs == []


async def test_is_bug_todo_returns_true_for_bug_kind(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("bug-slug")
    await todos_db.write_state("bug-slug", {"kind": "bug", "current": "input_assessment"})
    assert await todos_db.is_bug_todo("bug-slug") is True


async def test_is_bug_todo_returns_false_for_regular_todo(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("todo-slug")
    await todos_db.write_state("todo-slug", {"kind": "todo", "current": "input_assessment"})
    assert await todos_db.is_bug_todo("todo-slug") is False


async def test_has_pending_deferrals_false_when_no_artifact(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "pending"})
    assert await todos_db.has_pending_deferrals("my-slug") is False


async def test_has_pending_deferrals_true_when_artifact_exists(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "pending", "deferrals_processed": False})
    await todos_db.write_artifact("my-slug", "deferrals", "some deferrals")
    assert await todos_db.has_pending_deferrals("my-slug") is True


async def test_has_pending_deferrals_false_when_processed(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "pending", "deferrals_processed": True})
    await todos_db.write_artifact("my-slug", "deferrals", "some deferrals")
    assert await todos_db.has_pending_deferrals("my-slug") is False


async def test_write_state_raises_when_no_roadmap_entry(todos_db: TodosDb) -> None:
    """write_state fails fast when slug has no active/icebox roadmap entry."""
    with pytest.raises(ValueError, match="no active/icebox roadmap entry"):
        await todos_db.write_state("orphan", {"current": "pending"})


async def test_write_state_raises_when_slug_is_delivered(todos_db: TodosDb) -> None:
    """write_state fails fast for delivered slugs — deliver_sync owns that path."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})
    await todos_db.deliver("my-slug", commit="abc123")
    with pytest.raises(ValueError, match="no active/icebox roadmap entry"):
        await todos_db.write_state("my-slug", {"current": "should_fail"})


async def test_read_state_returns_none_for_delivered_slug(todos_db: TodosDb) -> None:
    """read_state returns None for delivered slugs — use read_state_delivered instead."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})
    await todos_db.deliver("my-slug", commit="abc123")
    assert await todos_db.read_state("my-slug") is None


async def test_read_state_delivered_returns_state_for_delivered_slug(todos_db: TodosDb) -> None:
    """read_state_delivered reads state for delivered slugs via roadmap ID join."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})
    await todos_db.deliver("my-slug", commit="abc123")
    result = await todos_db.read_state_delivered("my-slug")
    assert result is not None
    assert result["current"] == "delivered"


async def test_read_state_delivered_returns_none_for_active_slug(todos_db: TodosDb) -> None:
    """read_state_delivered returns None when the slug is not delivered."""
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "input_assessment"})
    assert await todos_db.read_state_delivered("my-slug") is None
