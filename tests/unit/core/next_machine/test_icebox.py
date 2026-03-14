"""Characterization tests for icebox manifest and folder movement behavior."""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import RoadmapEntry
from teleclaude.core.next_machine.icebox import (
    clean_dependency_references,
    freeze_to_icebox,
    load_icebox,
    migrate_icebox_to_subfolder,
    save_icebox,
    unfreeze_from_icebox,
)
from teleclaude.core.next_machine.roadmap import load_roadmap, save_roadmap


def test_load_icebox_returns_entries_from_subfolder_manifest(tmp_path: Path) -> None:
    save_icebox(
        str(tmp_path),
        [RoadmapEntry(slug="parked", group="holder", after=["dep"], description="keep me")],
    )

    entries = load_icebox(str(tmp_path))

    assert entries == [RoadmapEntry(slug="parked", group="holder", after=["dep"], description="keep me")]


def test_freeze_to_icebox_prepends_entry_and_moves_todo_directory(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="first", group=None, after=[], description=None),
            RoadmapEntry(slug="freeze-me", group=None, after=["dep"], description="target"),
        ],
    )
    todo_dir = tmp_path / "todos" / "freeze-me"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("content", encoding="utf-8")

    frozen = freeze_to_icebox(str(tmp_path), "freeze-me")

    assert frozen is True
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["first"]
    assert [entry.slug for entry in load_icebox(str(tmp_path))] == ["freeze-me"]
    assert not todo_dir.exists()
    assert (tmp_path / "todos" / "_icebox" / "freeze-me" / "input.md").exists()


def test_unfreeze_from_icebox_appends_entry_back_to_roadmap_and_moves_folder(tmp_path: Path) -> None:
    save_roadmap(str(tmp_path), [RoadmapEntry(slug="existing", group=None, after=[], description=None)])
    save_icebox(str(tmp_path), [RoadmapEntry(slug="thawed", group=None, after=[], description=None)])
    frozen_dir = tmp_path / "todos" / "_icebox" / "thawed"
    frozen_dir.mkdir(parents=True)
    (frozen_dir / "requirements.md").write_text("spec", encoding="utf-8")

    thawed = unfreeze_from_icebox(str(tmp_path), "thawed")

    assert thawed is True
    assert [entry.slug for entry in load_roadmap(str(tmp_path))] == ["existing", "thawed"]
    assert load_icebox(str(tmp_path)) == []
    assert not frozen_dir.exists()
    assert (tmp_path / "todos" / "thawed" / "requirements.md").exists()


def test_clean_dependency_references_removes_slug_from_roadmap_and_icebox_entries(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="road", group=None, after=["shared", "keep"], description=None),
            RoadmapEntry(slug="other", group=None, after=[], description=None),
        ],
    )
    save_icebox(
        str(tmp_path),
        [RoadmapEntry(slug="parked", group=None, after=["shared"], description=None)],
    )

    clean_dependency_references(str(tmp_path), "shared")

    assert load_roadmap(str(tmp_path))[0].after == ["keep"]
    assert load_icebox(str(tmp_path))[0].after == []


def test_migrate_icebox_to_subfolder_moves_manifest_and_listed_folders(tmp_path: Path) -> None:
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "legacy").mkdir()
    (todos_dir / "legacy" / "input.md").write_text("content", encoding="utf-8")
    (todos_dir / "icebox.yaml").write_text(
        yaml.safe_dump([{"slug": "legacy"}], sort_keys=False),
        encoding="utf-8",
    )

    moved = migrate_icebox_to_subfolder(str(tmp_path))

    assert moved == 1
    assert not (todos_dir / "icebox.yaml").exists()
    assert (todos_dir / "_icebox" / "icebox.yaml").exists()
    assert (todos_dir / "_icebox" / "legacy" / "input.md").exists()
