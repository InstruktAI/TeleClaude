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


def test_create_todo_skeleton_rejects_existing(tmp_path: Path) -> None:
    create_todo_skeleton(tmp_path, "sample-slug")

    with pytest.raises(FileExistsError):
        create_todo_skeleton(tmp_path, "sample-slug")


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

    todo_dir = tmp_path / "todos" / "test-slug"
    icebox_path = tmp_path / "todos" / "icebox.yaml"

    # Verify preconditions
    assert todo_dir.exists()
    icebox = yaml.safe_load(icebox_path.read_text(encoding="utf-8"))
    assert any(e["slug"] == "test-slug" for e in icebox)

    # Remove the todo
    remove_todo(tmp_path, "test-slug")

    # Verify directory is deleted
    assert not todo_dir.exists()

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
    icebox_path = tmp_path / "todos" / "icebox.yaml"
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
