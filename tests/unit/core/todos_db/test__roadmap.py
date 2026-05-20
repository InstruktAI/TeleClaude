"""RED tests for TodosDbRoadmapMixin — roadmap persistence."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import (
    RoadmapDep,
    TodoArtifact,
    TodoArtifactVersion,
    TodoRoadmap,
    TodoStateModel,
)
from teleclaude.core.todos_db._roadmap import ReactivateRefused

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


async def test_soft_remove_hides_entry_from_default_listings(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("my-slug")
    removed = await todos_db.soft_remove_from_roadmap("my-slug", cwd="/unused")
    assert removed is True
    assert await todos_db.list_roadmap() == []


async def test_soft_remove_nonexistent_returns_false(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    removed = await todos_db.soft_remove_from_roadmap("ghost", cwd="/unused")
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


async def test_set_deps_refuses_removed_slug(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("child")
    await todos_db.add_to_roadmap("parent")
    await todos_db.soft_remove_from_roadmap("child", cwd="/repo")

    with pytest.raises(ValueError):
        await todos_db.set_deps("child", after=["parent"])

    assert await todos_db.load_deps() == {}
    assert await todos_db.get_deps("child") == []


async def test_load_deps_filters_removed_rows(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("child")
    await todos_db.add_to_roadmap("live-parent")
    await todos_db.add_to_roadmap("removed-parent")
    await todos_db.add_to_roadmap("removed-child")
    _mark_removed(todos_db, "removed-parent")
    _mark_removed(todos_db, "removed-child")

    with todos_db._sync_session() as session:
        session.add(RoadmapDep(slug="child", depends_on="live-parent"))
        session.add(RoadmapDep(slug="child", depends_on="removed-parent"))
        session.add(RoadmapDep(slug="removed-child", depends_on="live-parent"))
        session.commit()

    assert await todos_db.load_deps() == {"child": ["live-parent"]}
    assert await todos_db.get_deps("removed-child") == []


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


def _mark_removed(todos_db: TodosDb, slug: str) -> str:
    """Force a slug's live row into the persisted removed state. Returns its row id."""
    with todos_db._sync_session() as session:
        entry = session.exec(
            select(TodoRoadmap).where(TodoRoadmap.slug == slug).where(TodoRoadmap.status != "removed").limit(1)
        ).one()
        entry.prev_status = entry.status
        entry.status = "removed"
        entry.removed_at = "2026-05-19T00:00:00+00:00"
        session.add(entry)
        session.commit()
        return entry.id


async def test_resolve_id_excludes_removed_by_default(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("ghosted")
    _mark_removed(todos_db, "ghosted")

    assert await todos_db.resolve_id("ghosted") is None
    assert todos_db.resolve_id_sync("ghosted") is None
    assert await todos_db.slug_in_roadmap("ghosted") is False


async def test_list_roadmap_omits_removed_entries(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("kept")
    await todos_db.add_to_roadmap("gone")
    _mark_removed(todos_db, "gone")

    slugs = [item["slug"] for item in await todos_db.list_roadmap(include_icebox=True, include_delivered=True)]
    assert slugs == ["kept"]


@pytest.fixture
def patched_cleanup(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand-in for cleanup_delivered_slug so soft-remove tests don't shell out."""
    cleanup = MagicMock()
    monkeypatch.setattr(
        "teleclaude.core.todos_db._roadmap.cleanup_delivered_slug",
        cleanup,
        raising=False,
    )
    return cleanup


async def test_soft_remove_retains_state_artifacts_and_versions(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("kept")
    await todos_db.write_state("kept", {"kind": "todo", "lifecycle_phase": "prepared"})
    await todos_db.write_artifact("kept", "prd", "v1")
    await todos_db.write_artifact("kept", "prd", "v2")
    row_id = await todos_db.resolve_id("kept")
    assert row_id is not None

    await todos_db.soft_remove_from_roadmap("kept", cwd="/repo")

    with todos_db._sync_session() as session:
        state_row = session.get(TodoStateModel, row_id)
        artifact = session.get(TodoArtifact, (row_id, "prd"))
        version_count = session.exec(select(TodoArtifactVersion).where(TodoArtifactVersion.id == row_id)).all()
    assert state_row is not None
    assert artifact is not None
    assert len(version_count) == 2


async def test_soft_remove_snapshots_outgoing_deps_and_scrubs_live_edges(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("a")
    await todos_db.add_to_roadmap("b")
    await todos_db.add_to_roadmap("victim")
    await todos_db.set_deps("victim", after=["a", "b"])
    await todos_db.add_to_roadmap("dependent")
    await todos_db.set_deps("dependent", after=["victim"])

    await todos_db.soft_remove_from_roadmap("victim", cwd="/repo")

    deps = await todos_db.load_deps()
    assert "victim" not in deps  # outgoing edges gone
    assert "victim" not in deps.get("dependent", [])  # inbound edges gone

    with todos_db._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "victim").limit(1)).one()
    assert entry.status == "removed"
    assert entry.prev_status == "active"
    assert entry.removed_at is not None
    assert json.loads(entry.removed_deps or "[]") == ["a", "b"]


async def test_soft_remove_permits_immediate_same_slug_creation(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("reusable")
    await todos_db.set_deps("reusable", after=["upstream-was-here"])
    old_id = await todos_db.resolve_id("reusable")
    await todos_db.soft_remove_from_roadmap("reusable", cwd="/repo")

    assert await todos_db.add_to_roadmap("reusable") is True
    new_id = await todos_db.resolve_id("reusable")
    assert new_id is not None
    assert new_id != old_id
    # The freshly created entry must not inherit the removed entry's edges.
    assert await todos_db.get_deps("reusable") == []


async def test_soft_remove_invokes_cleanup_for_non_draft_todos(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("real-work")
    await todos_db.write_state("real-work", {"kind": "todo", "lifecycle_phase": "prepared"})

    await todos_db.soft_remove_from_roadmap("real-work", cwd="/some/project")

    patched_cleanup.assert_called_once_with("/some/project", "real-work")


async def test_soft_remove_skips_cleanup_for_drafts(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("just-a-draft")
    await todos_db.write_state("just-a-draft", {"kind": "draft", "lifecycle_phase": "draft"})

    await todos_db.soft_remove_from_roadmap("just-a-draft", cwd="/some/project")

    patched_cleanup.assert_not_called()


async def test_reactivate_restores_prev_status_and_replays_outgoing_deps(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("a")
    await todos_db.add_to_roadmap("b")
    await todos_db.add_to_roadmap("target")
    await todos_db.freeze("target")
    await todos_db.set_deps("target", after=["a", "b"])
    await todos_db.write_state("target", {"kind": "todo", "lifecycle_phase": "prepared"})
    await todos_db.write_artifact("target", "prd", "body v1")
    await todos_db.write_artifact("target", "prd", "body v2")
    row_id = await todos_db.resolve_id("target")
    assert row_id is not None
    await todos_db.soft_remove_from_roadmap("target", cwd="/repo")

    restored_slug = await todos_db.reactivate_removed(row_id)

    assert restored_slug == "target"
    entries = await todos_db.list_roadmap(include_icebox=True)
    restored = next(e for e in entries if e["slug"] == "target")
    assert restored["status"] == "icebox"  # the pre-removal status was icebox
    assert await todos_db.get_deps("target") == ["a", "b"]
    # State and artifacts are addressable again through the default resolvers.
    state = await todos_db.read_state("target")
    assert state is not None
    assert await todos_db.read_artifact("target", "prd") == "body v2"
    versions = await todos_db.artifact_versions("target", "prd")
    assert [version["content"] for version in versions] == ["body v2", "body v1"]


async def test_reactivate_refuses_invalid_removed_deps_without_mutating(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("broken")
    row_id = await todos_db.resolve_id("broken")
    assert row_id is not None
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        entry.status = "removed"
        entry.prev_status = "active"
        entry.removed_at = "2026-05-19T00:00:00+00:00"
        entry.removed_deps = "{not-json"
        session.add(entry)
        session.commit()

    with pytest.raises(ReactivateRefused) as exc_info:
        await todos_db.reactivate_removed(row_id)

    assert exc_info.value.reason == "invalid_removed_deps"
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        assert entry.status == "removed"
        assert entry.removed_deps == "{not-json"


async def test_deliver_sync_refuses_removed_slug(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    await todos_db.add_to_roadmap("removed-work")
    row_id = await todos_db.resolve_id("removed-work")
    assert row_id is not None
    await todos_db.soft_remove_from_roadmap("removed-work", cwd="/repo")

    assert todos_db.deliver_sync("removed-work", commit="abc123") is False
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        assert entry.status == "removed"
        assert entry.delivered_at is None


async def test_reactivate_legacy_row_without_tombstone_falls_back_to_icebox(
    todos_db: TodosDb,
) -> None:
    """A pre-tombstone removed row (status=removed but no prev_status or removed_deps)
    must still be restorable; it lands in icebox with no edge replay."""
    await todos_db.add_to_roadmap("legacy")
    row_id = await todos_db.resolve_id("legacy")
    assert row_id is not None
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        entry.status = "removed"
        entry.removed_at = "2026-05-19T00:00:00+00:00"
        # prev_status and removed_deps deliberately left NULL
        session.add(entry)
        session.commit()

    restored = await todos_db.reactivate_removed(row_id)

    assert restored == "legacy"
    entries = await todos_db.list_roadmap(include_icebox=True)
    assert any(e["slug"] == "legacy" and e["status"] == "icebox" for e in entries)
    assert await todos_db.get_deps("legacy") == []


async def test_reactivate_refuses_when_live_twin_exists(todos_db: TodosDb, patched_cleanup: MagicMock) -> None:
    """Fail-closed: the operation refuses and does not mutate if a live entry
    already owns the slug. Test asserts the structured fields on the typed
    exception, not the message text."""
    await todos_db.add_to_roadmap("contested")
    removed_id = await todos_db.resolve_id("contested")
    assert removed_id is not None
    await todos_db.soft_remove_from_roadmap("contested", cwd="/repo")
    # A new live todo claims the same slug while the tombstone exists.
    await todos_db.add_to_roadmap("contested")
    live_id = await todos_db.resolve_id("contested")
    assert live_id is not None
    assert live_id != removed_id

    with pytest.raises(ReactivateRefused) as exc_info:
        await todos_db.reactivate_removed(removed_id)
    assert exc_info.value.reason == "live_twin_exists"
    assert exc_info.value.roadmap_id == removed_id
    assert exc_info.value.slug == "contested"

    # The removed row must be unchanged (still removed; no mutation).
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, removed_id)
        assert entry is not None
        assert entry.status == "removed"


async def test_reactivate_refuses_when_id_is_not_a_removed_row(todos_db: TodosDb) -> None:
    """The operation only acts on removed rows; passing a live or unknown id refuses."""
    await todos_db.add_to_roadmap("alive")
    live_id = await todos_db.resolve_id("alive")
    assert live_id is not None

    with pytest.raises(ReactivateRefused) as exc_info:
        await todos_db.reactivate_removed(live_id)
    assert exc_info.value.reason == "not_removed"

    with pytest.raises(ReactivateRefused) as exc_info:
        await todos_db.reactivate_removed("does-not-exist")
    assert exc_info.value.reason == "not_removed"
