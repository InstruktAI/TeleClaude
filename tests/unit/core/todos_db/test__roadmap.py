"""RED tests for TodosDbRoadmapMixin — roadmap persistence."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


async def test_list_roadmap_empty_by_default(todos_db: TodosDb) -> None:
    items = await todos_db.list_roadmap()
    assert items == []


async def test_add_to_roadmap_creates_entry(todos_db: TodosDb) -> None:
    added = await todos_db.add_to_roadmap("my-slug", description="A task")
    assert added is True
    items = await todos_db.list_roadmap()
    assert len(items) == 1
    assert items[0]["slug"] == "my-slug"
    assert items[0]["status"] == "active"


async def test_add_duplicate_slug_is_idempotent(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    result = await todos_db.add_to_roadmap("my-slug")
    assert result is True
    items = await todos_db.list_roadmap()
    assert len(items) == 1


async def test_add_duplicate_slug_updates_group(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.add_to_roadmap("my-slug", group_slug="my-group")
    items = await todos_db.list_roadmap()
    assert len(items) == 1
    assert items[0]["group_slug"] == "my-group"


async def test_add_duplicate_slug_updates_description(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug", description="old")
    await todos_db.add_to_roadmap("my-slug", description="new")
    items = await todos_db.list_roadmap()
    assert len(items) == 1
    assert items[0]["description"] == "new"


async def test_roadmap_preserves_insertion_order(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("alpha")
    await todos_db.add_to_roadmap("beta")
    await todos_db.add_to_roadmap("gamma")
    items = await todos_db.list_roadmap()
    assert [i["slug"] for i in items] == ["alpha", "beta", "gamma"]


async def test_remove_from_roadmap(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    removed = await todos_db.remove_from_roadmap("my-slug")
    assert removed is True
    assert await todos_db.list_roadmap() == []


async def test_remove_nonexistent_returns_false(todos_db: TodosDb) -> None:
    removed = await todos_db.remove_from_roadmap("ghost")
    assert removed is False


async def test_slug_in_roadmap(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("exists")
    assert await todos_db.slug_in_roadmap("exists") is True
    assert await todos_db.slug_in_roadmap("missing") is False


async def test_deliver_marks_status_delivered(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    delivered = await todos_db.deliver("my-slug", commit="abc123")
    assert delivered is True
    items = await todos_db.list_roadmap()
    assert items == []  # delivered items excluded by default
    items = await todos_db.list_roadmap(include_delivered=True)
    delivered_items = [i for i in items if i["status"] == "delivered"]
    assert len(delivered_items) == 1
    assert delivered_items[0]["delivered_commit"] == "abc123"


async def test_delivered_slugs_returns_set(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("done-1")
    await todos_db.add_to_roadmap("done-2")
    await todos_db.add_to_roadmap("active")
    await todos_db.deliver("done-1")
    await todos_db.deliver("done-2")
    slugs = await todos_db.delivered_slugs()
    assert slugs == {"done-1", "done-2"}


async def test_freeze_moves_to_icebox(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("freezable")
    await todos_db.freeze("freezable")
    active = await todos_db.list_roadmap()
    assert len(active) == 0
    with_icebox = await todos_db.list_roadmap(include_icebox=True)
    assert len(with_icebox) == 1
    assert with_icebox[0]["status"] == "icebox"


async def test_unfreeze_restores_to_active(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("freezable")
    await todos_db.freeze("freezable")
    await todos_db.unfreeze("freezable")
    active = await todos_db.list_roadmap()
    assert len(active) == 1
    assert active[0]["status"] == "active"


async def test_set_deps_and_load_deps(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("child")
    await todos_db.add_to_roadmap("parent-a")
    await todos_db.add_to_roadmap("parent-b")
    await todos_db.set_deps("child", after=["parent-a", "parent-b"])
    deps = await todos_db.load_deps()
    assert deps["child"] == ["parent-a", "parent-b"]


async def test_set_deps_replaces_previous(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("child")
    await todos_db.add_to_roadmap("old-dep")
    await todos_db.add_to_roadmap("new-dep")
    await todos_db.set_deps("child", after=["old-dep"])
    await todos_db.set_deps("child", after=["new-dep"])
    deps = await todos_db.load_deps()
    assert deps["child"] == ["new-dep"]


async def test_add_with_group(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("parent")
    await todos_db.add_to_roadmap("child", group_slug="parent")
    items = await todos_db.list_roadmap()
    child = next(i for i in items if i["slug"] == "child")
    assert child["group_slug"] == "parent"


async def test_clean_dep_references_removes_slug_from_deps(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("a")
    await todos_db.add_to_roadmap("b")
    await todos_db.set_deps("b", after=["a"])
    await todos_db.clean_dep_references("a")
    deps = await todos_db.load_deps()
    assert "a" not in deps.get("b", [])


async def test_move_in_roadmap_reorders(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("first")
    await todos_db.add_to_roadmap("second")
    await todos_db.add_to_roadmap("third")
    await todos_db.move_in_roadmap("third", before="first")
    items = await todos_db.list_roadmap()
    assert [i["slug"] for i in items] == ["third", "first", "second"]
