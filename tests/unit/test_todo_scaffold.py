"""Tests for todo scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.todo_scaffold import create_todo_skeleton


def test_create_todo_skeleton_creates_expected_files(tmp_path: Path) -> None:
    todo_dir = create_todo_skeleton(tmp_path, "sample-slug")

    assert todo_dir == tmp_path / "todos" / "sample-slug"
    assert (todo_dir / "requirements.md").exists()
    assert (todo_dir / "implementation-plan.md").exists()
    assert (todo_dir / "quality-checklist.md").exists()
    assert (todo_dir / "state.json").exists()
    assert not (todo_dir / "input.md").exists()


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
