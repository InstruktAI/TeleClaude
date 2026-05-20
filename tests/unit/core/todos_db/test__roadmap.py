"""RED tests for TodosDbRoadmapMixin — roadmap persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._exceptions import RemoveRefused
from teleclaude.core.todos_db._models import (
    RoadmapDep,
    TodoArtifact,
    TodoArtifactVersion,
    TodoRoadmap,
    TodoStateModel,
)
from teleclaude.core.todos_db._roadmap import ReactivateRefused
from teleclaude.docs_reconcile import scan_remove_orphans

pytestmark = pytest.mark.asyncio

_RenameRoadmapSlug = Callable[[str, str], Awaitable[bool]]


def _rename_roadmap_slug(todos_db: TodosDb) -> _RenameRoadmapSlug:
    return cast(_RenameRoadmapSlug, todos_db.rename_roadmap_slug)


def _set_roadmap_children(todos_db: TodosDb, slug: str, children: list[str]) -> None:
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "UPDATE roadmap SET children = ? WHERE slug = ? AND status != ?",  # guard: raw-sql
            (json.dumps(children), slug, "delivered"),
        )
        conn.commit()
    finally:
        conn.close()


def _project_root(todos_db: TodosDb) -> Path:
    return Path(todos_db.db_path).parent


def _write_delivered_by_snippet(project_root: Path, delivered_by: list[str]) -> Path:
    snippet_path = project_root / "docs" / "project" / "spec" / "remove-guard.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/remove-guard\n"
            "type: spec\n"
            "scope: project\n"
            "description: Remove guard\n"
            "status: target\n"
            f"delivered_by: {delivered_by}\n"
            "---\n"
            "# Remove Guard\n\n"
            "## What it is\n"
            "A remove guard.\n\n"
            "## Canonical fields\n"
            "Fields.\n"
        ),
        encoding="utf-8",
    )
    return snippet_path


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


async def test_soft_remove_refuses_when_slug_is_sole_live_snippet_deliverer(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("candidate")
    project_root = _project_root(todos_db)
    snippet_path = _write_delivered_by_snippet(project_root, ["candidate"])
    before = snippet_path.read_bytes()

    with pytest.raises(RemoveRefused) as exc_info:
        await todos_db.soft_remove_from_roadmap("candidate", cwd=str(project_root))

    assert exc_info.value.blocking_snippets[0].path == str(snippet_path)
    assert exc_info.value.blocking_snippets[0].slug_role == "sole"
    with todos_db._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "candidate").limit(1)).one()
    assert entry.status == "active"
    assert snippet_path.read_bytes() == before
    patched_cleanup.assert_not_called()


async def test_soft_remove_refuses_when_other_deliverers_are_already_removed(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("candidate")
    await todos_db.add_to_roadmap("removed-sibling")
    _mark_removed(todos_db, "removed-sibling")
    project_root = _project_root(todos_db)
    _write_delivered_by_snippet(project_root, ["candidate", "removed-sibling"])

    with pytest.raises(RemoveRefused) as exc_info:
        await todos_db.soft_remove_from_roadmap("candidate", cwd=str(project_root))

    assert exc_info.value.blocking_snippets[0].slug_role == "last_live_among_removed"
    assert exc_info.value.blocking_snippets[0].other_removed_deliverers == ["removed-sibling"]
    with todos_db._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "candidate").limit(1)).one()
    assert entry.status == "active"
    patched_cleanup.assert_not_called()


async def test_soft_remove_allows_shared_live_deliverer_without_mutating_snippet(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("candidate")
    await todos_db.add_to_roadmap("live-sibling")
    project_root = _project_root(todos_db)
    snippet_path = _write_delivered_by_snippet(project_root, ["candidate", "live-sibling"])
    before = snippet_path.read_bytes()

    removed = await todos_db.soft_remove_from_roadmap("candidate", cwd=str(project_root))

    assert removed is True
    assert snippet_path.read_bytes() == before
    with todos_db._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "candidate").limit(1)).one()
    assert entry.status == "removed"
    assert (
        scan_remove_orphans(
            project_root,
            "candidate",
            {
                "candidate": "removed",
                "live-sibling": "active",
            },
        )
        == []
    )


async def test_concurrent_soft_removes_against_shared_snippet_leave_one_live_deliverer(
    todos_db: TodosDb, patched_cleanup: MagicMock
) -> None:
    await todos_db.add_to_roadmap("first")
    await todos_db.add_to_roadmap("second")
    project_root = _project_root(todos_db)
    _write_delivered_by_snippet(project_root, ["first", "second"])

    results = await asyncio.gather(
        todos_db.soft_remove_from_roadmap("first", cwd=str(project_root)),
        todos_db.soft_remove_from_roadmap("second", cwd=str(project_root)),
        return_exceptions=True,
    )

    assert sorted(type(result).__name__ for result in results) == ["RemoveRefused", "bool"]
    assert sum(result is True for result in results) == 1
    with todos_db._sync_session() as session:
        rows = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug.in_(("first", "second")))).all()
    assert sorted(row.status for row in rows) == ["active", "removed"]


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


async def test_list_expired_removed_returns_pending_purge_paths(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("expired")
    row_id = _mark_removed(todos_db, "expired")
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        entry.pending_purge_paths = json.dumps(["docs/a.md", "docs/b.md"])
        session.add(entry)
        session.commit()

    rows = await todos_db.list_expired_removed("2026-05-20T00:00:00+00:00")

    assert rows == [
        {
            "id": row_id,
            "slug": "expired",
            "removed_at": "2026-05-19T00:00:00+00:00",
            "pending_purge_paths": ["docs/a.md", "docs/b.md"],
        }
    ]


async def test_pending_purge_paths_round_trip_through_set_and_clear(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("expired")
    row_id = _mark_removed(todos_db, "expired")

    await todos_db.set_pending_purge_paths(row_id, ["docs/a.md"])

    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        assert json.loads(entry.pending_purge_paths or "null") == ["docs/a.md"]

    await todos_db.clear_pending_purge_paths(row_id)

    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        assert entry.pending_purge_paths is None


async def test_purge_one_removed_deletes_only_the_addressed_removed_row(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("first")
    await todos_db.add_to_roadmap("second")
    first_id = _mark_removed(todos_db, "first")
    second_id = _mark_removed(todos_db, "second")

    purged = await todos_db.purge_one_removed(first_id)

    assert purged == {
        "id": first_id,
        "slug": "first",
        "removed_at": "2026-05-19T00:00:00+00:00",
    }
    with todos_db._sync_session() as session:
        assert session.get(TodoRoadmap, first_id) is None
        assert session.get(TodoRoadmap, second_id) is not None


async def test_list_expired_removed_self_heals_legacy_null_removed_at(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("legacy")
    row_id = _mark_removed(todos_db, "legacy")
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        entry.removed_at = None
        session.add(entry)
        session.commit()

    rows = await todos_db.list_expired_removed("2000-01-01T00:00:00+00:00")

    assert rows == []
    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        assert entry.removed_at is not None


async def test_purge_expired_removed_wrapper_preserves_hard_delete_compatibility(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("expired")
    row_id = _mark_removed(todos_db, "expired")

    purged = await todos_db.purge_expired_removed("2026-05-20T00:00:00+00:00")

    assert purged == [
        {
            "id": row_id,
            "slug": "expired",
            "removed_at": "2026-05-19T00:00:00+00:00",
        }
    ]
    with todos_db._sync_session() as session:
        assert session.get(TodoRoadmap, row_id) is None


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


async def test_rename_roadmap_slug_rekeys_active_entry_groups_children_and_deps(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("old-slug")
    await todos_db.deliver("old-slug", commit="abc123", children=["old-slug"])
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("container")
    await todos_db.add_to_roadmap("upstream")
    await todos_db.add_to_roadmap("old-slug", group_slug="holder", after=["upstream"])
    await todos_db.add_to_roadmap("downstream", after=["old-slug"])
    _set_roadmap_children(todos_db, "container", ["old-slug", "sibling"])

    renamed = await _rename_roadmap_slug(todos_db)("old-slug", "new-slug")

    assert renamed is True
    active = await todos_db.list_roadmap()
    active_by_slug = {row["slug"]: row for row in active}
    assert "old-slug" not in active_by_slug
    assert active_by_slug["new-slug"]["group_slug"] == "holder"
    assert active_by_slug["container"]["children"] == ["new-slug", "sibling"]
    assert await todos_db.load_deps() == {"downstream": ["new-slug"], "new-slug": ["upstream"]}
    delivered = [row for row in await todos_db.list_roadmap(include_delivered=True) if row["status"] == "delivered"]
    assert len(delivered) == 1
    assert delivered[0]["slug"] == "old-slug"
    assert delivered[0]["children"] == ["old-slug"]
