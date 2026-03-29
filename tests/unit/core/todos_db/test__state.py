"""RED tests for TodosDbStateMixin — todo state persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


async def test_read_state_returns_none_for_unknown_slug(todos_db: TodosDb) -> None:
    result = await todos_db.read_state("nonexistent")
    assert result is None


async def test_write_then_read_state_round_trips(todos_db: TodosDb) -> None:
    state = {"schema_version": 2, "current": "input_assessment", "phase": "pending"}
    await todos_db.write_state("my-slug", state)
    result = await todos_db.read_state("my-slug")
    assert result is not None
    assert result["current"] == "input_assessment"
    assert result["schema_version"] == 2


async def test_write_state_updates_existing_row(todos_db: TodosDb) -> None:
    state_v1 = {"schema_version": 2, "current": "input_assessment"}
    await todos_db.write_state("my-slug", state_v1)

    state_v2 = {"schema_version": 2, "current": "prepared"}
    await todos_db.write_state("my-slug", state_v2)

    result = await todos_db.read_state("my-slug")
    assert result is not None
    assert result["current"] == "prepared"


async def test_delete_state_removes_row(todos_db: TodosDb) -> None:
    await todos_db.write_state("my-slug", {"current": "pending"})
    await todos_db.delete_state("my-slug")
    assert await todos_db.read_state("my-slug") is None


async def test_list_slugs_returns_all_stored(todos_db: TodosDb) -> None:
    await todos_db.write_state("alpha", {"current": "pending"})
    await todos_db.write_state("beta", {"current": "prepared"})
    slugs = await todos_db.list_slugs()
    assert set(slugs) == {"alpha", "beta"}


async def test_list_slugs_empty_when_no_state(todos_db: TodosDb) -> None:
    slugs = await todos_db.list_slugs()
    assert slugs == []
