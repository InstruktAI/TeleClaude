"""Tests for todo scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.todo_scaffold import create_todo_skeleton, remove_todo


def test_create_todo_skeleton_creates_expected_files(tmp_path: Path) -> None:
    todo_dir = create_todo_skeleton(tmp_path, "sample-slug")

    assert todo_dir == tmp_path / "todos" / "sample-slug"
    assert (todo_dir / "requirements.md").exists()
    assert (todo_dir / "implementation-plan.md").exists()
    assert (todo_dir / "quality-checklist.md").exists()
    assert (todo_dir / "demo.md").exists()
    assert (todo_dir / "state.yaml").exists()
    assert (todo_dir / "input.md").exists()

    # Verify input.md has correct heading
    content = (todo_dir / "input.md").read_text()
    assert "# Input: sample-slug" in content

    # Verify demo.md has correct heading
    demo_content = (todo_dir / "demo.md").read_text()
    assert "# Demo: sample-slug" in demo_content


def test_create_todo_skeleton_uses_counter_suffix_on_collision(tmp_path: Path) -> None:
    first = create_todo_skeleton(tmp_path, "sample-slug")
    assert first.name == "sample-slug"

    second = create_todo_skeleton(tmp_path, "sample-slug")
    assert second.name == "sample-slug-2"

    third = create_todo_skeleton(tmp_path, "sample-slug")
    assert third.name == "sample-slug-3"


def test_create_todo_skeleton_registers_in_roadmap_when_after_provided(tmp_path: Path) -> None:
    create_todo_skeleton(tmp_path, "sample-slug", after=["dep-b", "dep-a", "dep-a"])

    import yaml

    roadmap = yaml.safe_load((tmp_path / "todos" / "roadmap.yaml").read_text(encoding="utf-8"))
    entry = next(e for e in roadmap if e["slug"] == "sample-slug")
    assert entry["after"] == ["dep-b", "dep-a"]


def test_create_todo_skeleton_validates_slug(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_todo_skeleton(tmp_path, "Bad Slug")


def test_remove_todo_removes_directory_and_roadmap_entry(tmp_path: Path) -> None:
    """Test remove_todo with a normal slug: directory deleted, roadmap entry removed."""
    import yaml

    # Create a todo and add to roadmap
    create_todo_skeleton(tmp_path, "test-slug", after=["dep-a"])
    todo_dir = tmp_path / "todos" / "test-slug"
    roadmap_path = tmp_path / "todos" / "roadmap.yaml"

    # Verify preconditions
    assert todo_dir.exists()
    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))
    assert any(e["slug"] == "test-slug" for e in roadmap)

    # Remove the todo
    remove_todo(tmp_path, "test-slug")

    # Verify directory is deleted
    assert not todo_dir.exists()

    # Verify roadmap entry is removed
    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))
    assert not any(e["slug"] == "test-slug" for e in roadmap)


def test_remove_todo_removes_from_icebox(tmp_path: Path) -> None:
    """Test remove_todo with an icebox slug: directory deleted, icebox entry removed."""
    import yaml

    from teleclaude.core.next_machine.core import freeze_to_icebox

    # Create a todo, add to roadmap, then freeze to icebox
    create_todo_skeleton(tmp_path, "test-slug", after=[])
    freeze_to_icebox(str(tmp_path), "test-slug")

    icebox_slug_dir = tmp_path / "todos" / "_icebox" / "test-slug"
    icebox_path = tmp_path / "todos" / "_icebox" / "icebox.yaml"

    # Verify preconditions (folder moved to _icebox/)
    assert icebox_slug_dir.exists()
    icebox = yaml.safe_load(icebox_path.read_text(encoding="utf-8"))
    assert any(e["slug"] == "test-slug" for e in icebox)

    # Remove the todo
    remove_todo(tmp_path, "test-slug")

    # Verify directory is deleted from _icebox/
    assert not icebox_slug_dir.exists()

    # Verify icebox entry is removed
    icebox = yaml.safe_load(icebox_path.read_text(encoding="utf-8"))
    assert not any(e["slug"] == "test-slug" for e in icebox)


def test_remove_todo_cleans_up_dependency_references(tmp_path: Path) -> None:
    """Test remove_todo cleans up `after` references in roadmap and icebox."""
    import yaml

    from teleclaude.core.next_machine.core import freeze_to_icebox

    # Create slugs: dep1 -> dep2 -> dep3
    create_todo_skeleton(tmp_path, "dep1", after=[])
    create_todo_skeleton(tmp_path, "dep2", after=["dep1"])
    create_todo_skeleton(tmp_path, "dep3", after=["dep2"])

    # Freeze dep3 to icebox
    freeze_to_icebox(str(tmp_path), "dep3")

    # Remove dep1
    remove_todo(tmp_path, "dep1")

    # Verify dep2's after list no longer contains dep1
    roadmap_path = tmp_path / "todos" / "roadmap.yaml"
    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))
    dep2_entry = next(e for e in roadmap if e["slug"] == "dep2")
    assert "dep1" not in dep2_entry.get("after", [])

    # Verify dep3's after list still contains dep2 (not affected)
    icebox_path = tmp_path / "todos" / "_icebox" / "icebox.yaml"
    icebox = yaml.safe_load(icebox_path.read_text(encoding="utf-8"))
    dep3_entry = next(e for e in icebox if e["slug"] == "dep3")
    assert "dep2" in dep3_entry.get("after", [])


def test_remove_todo_raises_error_when_worktree_exists(tmp_path: Path) -> None:
    """Test remove_todo raises RuntimeError when worktree exists."""
    create_todo_skeleton(tmp_path, "test-slug", after=[])

    # Create a fake worktree directory
    worktree_path = tmp_path / "trees" / "test-slug"
    worktree_path.mkdir(parents=True)

    # Attempt to remove should raise RuntimeError
    with pytest.raises(RuntimeError, match="worktree exists"):
        remove_todo(tmp_path, "test-slug")

    # Verify directory and roadmap entry still exist
    assert (tmp_path / "todos" / "test-slug").exists()


def test_remove_todo_raises_error_when_slug_not_found(tmp_path: Path) -> None:
    """Test remove_todo raises FileNotFoundError when slug not found anywhere."""
    # Attempt to remove non-existent slug
    with pytest.raises(FileNotFoundError, match="not found"):
        remove_todo(tmp_path, "nonexistent-slug")


# ── New _icebox/ layout tests ──────────────────────────────────────────────────


def test_freeze_moves_folder_to_icebox(tmp_path: Path) -> None:
    """freeze_to_icebox must move the slug folder into todos/_icebox/."""
    import yaml

    from teleclaude.core.next_machine.core import freeze_to_icebox

    create_todo_skeleton(tmp_path, "freeze-me", after=[])
    assert (tmp_path / "todos" / "freeze-me").exists()

    result = freeze_to_icebox(str(tmp_path), "freeze-me")
    assert result is True
    assert not (tmp_path / "todos" / "freeze-me").exists()
    assert (tmp_path / "todos" / "_icebox" / "freeze-me").exists()
    icebox = yaml.safe_load((tmp_path / "todos" / "_icebox" / "icebox.yaml").read_text())
    assert any(e["slug"] == "freeze-me" for e in icebox)


def test_freeze_without_folder_succeeds(tmp_path: Path) -> None:
    """freeze_to_icebox must succeed even when the slug folder doesn't exist."""
    import yaml

    from teleclaude.core.next_machine.core import RoadmapEntry, freeze_to_icebox, save_roadmap

    (tmp_path / "todos").mkdir(parents=True, exist_ok=True)
    save_roadmap(str(tmp_path), [RoadmapEntry(slug="no-folder-slug")])

    result = freeze_to_icebox(str(tmp_path), "no-folder-slug")
    assert result is True
    icebox = yaml.safe_load((tmp_path / "todos" / "_icebox" / "icebox.yaml").read_text())
    assert any(e["slug"] == "no-folder-slug" for e in icebox)


def test_unfreeze_moves_folder_back(tmp_path: Path) -> None:
    """unfreeze_from_icebox must move the folder back to todos/ and update YAML."""
    import yaml

    from teleclaude.core.next_machine.core import freeze_to_icebox, unfreeze_from_icebox

    create_todo_skeleton(tmp_path, "unfreeze-me", after=[])
    freeze_to_icebox(str(tmp_path), "unfreeze-me")
    assert (tmp_path / "todos" / "_icebox" / "unfreeze-me").exists()

    result = unfreeze_from_icebox(str(tmp_path), "unfreeze-me")
    assert result is True
    assert (tmp_path / "todos" / "unfreeze-me").exists()
    assert not (tmp_path / "todos" / "_icebox" / "unfreeze-me").exists()

    roadmap = yaml.safe_load((tmp_path / "todos" / "roadmap.yaml").read_text())
    assert any(e["slug"] == "unfreeze-me" for e in roadmap)


def test_unfreeze_nonexistent_slug_returns_false(tmp_path: Path) -> None:
    """unfreeze_from_icebox must return False for unknown slugs."""
    from teleclaude.core.next_machine.core import unfreeze_from_icebox

    (tmp_path / "todos" / "_icebox").mkdir(parents=True, exist_ok=True)
    (tmp_path / "todos" / "_icebox" / "icebox.yaml").write_text("[]")

    result = unfreeze_from_icebox(str(tmp_path), "ghost-slug")
    assert result is False


def test_remove_todo_from_icebox_location(tmp_path: Path) -> None:
    """remove_todo must delete a slug whose folder is in _icebox/."""
    import yaml

    from teleclaude.core.next_machine.core import freeze_to_icebox

    create_todo_skeleton(tmp_path, "frozen-remove", after=[])
    freeze_to_icebox(str(tmp_path), "frozen-remove")
    assert (tmp_path / "todos" / "_icebox" / "frozen-remove").exists()

    remove_todo(tmp_path, "frozen-remove")

    assert not (tmp_path / "todos" / "_icebox" / "frozen-remove").exists()
    icebox = yaml.safe_load((tmp_path / "todos" / "_icebox" / "icebox.yaml").read_text())
    assert not any(e["slug"] == "frozen-remove" for e in icebox)


def test_migrate_icebox_moves_folders(tmp_path: Path) -> None:
    """migrate_icebox_to_subfolder must move folders and relocate icebox.yaml."""
    import yaml

    from teleclaude.core.next_machine.core import migrate_icebox_to_subfolder

    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "roadmap.yaml").write_text("[]")
    (todos / "icebox.yaml").write_text(yaml.dump([{"slug": "old-frozen"}]))
    (todos / "old-frozen").mkdir()
    (todos / "old-frozen" / "state.yaml").write_text("{}")

    count = migrate_icebox_to_subfolder(str(tmp_path))
    assert count == 1
    assert not (todos / "icebox.yaml").exists()
    assert (todos / "_icebox" / "icebox.yaml").exists()
    assert not (todos / "old-frozen").exists()
    assert (todos / "_icebox" / "old-frozen").exists()


def test_migrate_icebox_idempotent(tmp_path: Path) -> None:
    """Running migrate_icebox_to_subfolder twice must be safe."""
    import yaml

    from teleclaude.core.next_machine.core import migrate_icebox_to_subfolder

    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "icebox.yaml").write_text(yaml.dump([{"slug": "already-moved"}]))
    icebox_sub = todos / "_icebox"
    icebox_sub.mkdir()
    (icebox_sub / "icebox.yaml").write_text(yaml.dump([{"slug": "already-moved"}]))

    # First run — old icebox.yaml exists, so it should detect it and migrate
    migrate_icebox_to_subfolder(str(tmp_path))
    # Second run — already migrated, should return 0
    count2 = migrate_icebox_to_subfolder(str(tmp_path))
    assert count2 == 0
