"""Legacy filesystem icebox manifest helpers for characterization tests."""

# pylint: disable=duplicate-code  # Legacy roadmap/icebox YAML helpers intentionally mirror each other.

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import RoadmapDict, RoadmapEntry
from teleclaude.core.next_machine.roadmap import load_roadmap, save_roadmap


def _icebox_dir(cwd: str) -> Path:
    return Path(cwd) / "todos" / "_icebox"


def _icebox_manifest_path(cwd: str) -> Path:
    return _icebox_dir(cwd) / "icebox.yaml"


def load_icebox(cwd: str) -> list[RoadmapEntry]:
    """Load icebox entries from the legacy YAML manifest."""
    path = _icebox_manifest_path(cwd)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        return []
    entries: list[RoadmapEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        data = item
        entries.append(
            RoadmapEntry(
                slug=str(data.get("slug", "")),
                group=str(data["group"]) if data.get("group") is not None else None,
                after=[str(dep) for dep in data.get("after", [])] if isinstance(data.get("after", []), list) else [],
                description=str(data["description"]) if data.get("description") is not None else None,
            )
        )
    return entries


def save_icebox(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write icebox entries to the legacy YAML manifest."""
    path = _icebox_manifest_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: list[RoadmapDict] = []
    for entry in entries:
        row: RoadmapDict = {"slug": entry.slug}
        if entry.group is not None:
            row["group"] = entry.group
        if entry.after:
            row["after"] = list(entry.after)
        if entry.description is not None:
            row["description"] = entry.description
        payload.append(row)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def freeze_to_icebox(cwd: str, slug: str) -> bool:
    """Move a roadmap entry and todo folder into the legacy icebox location."""
    roadmap = load_roadmap(cwd)
    target = next((entry for entry in roadmap if entry.slug == slug), None)
    if target is None:
        return False
    save_roadmap(cwd, [entry for entry in roadmap if entry.slug != slug])
    save_icebox(cwd, [target, *load_icebox(cwd)])

    todo_dir = Path(cwd) / "todos" / slug
    frozen_dir = _icebox_dir(cwd) / slug
    if todo_dir.exists():
        frozen_dir.parent.mkdir(parents=True, exist_ok=True)
        if frozen_dir.exists():
            shutil.rmtree(frozen_dir)
        shutil.move(str(todo_dir), str(frozen_dir))
    return True


def unfreeze_from_icebox(cwd: str, slug: str) -> bool:
    """Move an iceboxed entry and folder back into the active roadmap."""
    icebox = load_icebox(cwd)
    target = next((entry for entry in icebox if entry.slug == slug), None)
    if target is None:
        return False
    save_icebox(cwd, [entry for entry in icebox if entry.slug != slug])
    roadmap = load_roadmap(cwd)
    save_roadmap(cwd, [*roadmap, target])

    frozen_dir = _icebox_dir(cwd) / slug
    todo_dir = Path(cwd) / "todos" / slug
    if frozen_dir.exists():
        todo_dir.parent.mkdir(parents=True, exist_ok=True)
        if todo_dir.exists():
            shutil.rmtree(todo_dir)
        shutil.move(str(frozen_dir), str(todo_dir))
    return True


def clean_dependency_references(cwd: str, slug: str) -> None:
    """Remove a dependency slug from roadmap and icebox manifests."""
    roadmap = [
        RoadmapEntry(entry.slug, entry.group, [dep for dep in entry.after if dep != slug], entry.description)
        for entry in load_roadmap(cwd)
    ]
    icebox = [
        RoadmapEntry(entry.slug, entry.group, [dep for dep in entry.after if dep != slug], entry.description)
        for entry in load_icebox(cwd)
    ]
    save_roadmap(cwd, roadmap)
    save_icebox(cwd, icebox)


def migrate_icebox_to_subfolder(cwd: str) -> int:
    """Move legacy todos/icebox.yaml and listed todo folders into todos/_icebox."""
    todos_dir = Path(cwd) / "todos"
    legacy_manifest = todos_dir / "icebox.yaml"
    if not legacy_manifest.exists():
        return 0

    raw = yaml.safe_load(legacy_manifest.read_text(encoding="utf-8")) or []
    entries = load_icebox(cwd)
    if not entries and isinstance(raw, list):
        migrated_entries: list[RoadmapEntry] = []
        for item in raw:
            if isinstance(item, dict) and item.get("slug"):
                migrated_entries.append(RoadmapEntry(slug=str(item["slug"])))
        save_icebox(cwd, migrated_entries)
        entries = migrated_entries

    moved = 0
    icebox_dir = _icebox_dir(cwd)
    icebox_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        source = todos_dir / entry.slug
        target = icebox_dir / entry.slug
        if source.exists():
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source), str(target))
            moved += 1

    legacy_manifest.unlink(missing_ok=True)
    return moved
