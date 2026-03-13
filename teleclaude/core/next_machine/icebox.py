"""Icebox management — load, save, freeze/unfreeze todos/_icebox/icebox.yaml.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import RoadmapDict, RoadmapEntry
from teleclaude.core.next_machine.roadmap import load_roadmap, save_roadmap
from teleclaude.core.next_machine.state_io import read_text_sync, write_text_sync


def _icebox_dir(cwd: str) -> Path:
    """Return the _icebox/ directory path (todos/_icebox)."""
    return Path(cwd) / "todos" / "_icebox"


def _icebox_path(cwd: str) -> Path:
    return _icebox_dir(cwd) / "icebox.yaml"


def load_icebox(cwd: str) -> list[RoadmapEntry]:
    """Parse todos/icebox.yaml and return ordered list of entries."""
    path = _icebox_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[RoadmapEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        after = item.get("after")
        entries.append(
            RoadmapEntry(
                slug=item["slug"],
                group=item.get("group"),
                after=list(after) if isinstance(after, list) else [],
                description=item.get("description"),
            )
        )
    return entries


def save_icebox(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write entries back to todos/icebox.yaml."""
    path = _icebox_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[RoadmapDict] = []
    for entry in entries:
        item: RoadmapDict = {"slug": entry.slug}
        if entry.group:
            item["group"] = entry.group
        if entry.after:
            item["after"] = entry.after
        if entry.description:
            item["description"] = entry.description
        data.append(item)

    header = "# Parked work items. Promote back to roadmap.yaml when priority changes.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def load_icebox_slugs(cwd: str) -> list[str]:
    """Return slug strings in icebox order."""
    return [e.slug for e in load_icebox(cwd)]


def remove_from_icebox(cwd: str, slug: str) -> bool:
    """Remove entry from icebox.yaml. Returns True if found and removed."""
    entries = load_icebox(cwd)
    original_len = len(entries)
    entries = [e for e in entries if e.slug != slug]
    if len(entries) < original_len:
        save_icebox(cwd, entries)
        return True
    return False


def clean_dependency_references(cwd: str, slug: str) -> None:
    """Remove a slug from all `after` dependency lists in roadmap and icebox.

    Args:
        cwd: Project root directory
        slug: Slug to remove from dependency lists
    """
    # Clean roadmap
    roadmap_entries = load_roadmap(cwd)
    roadmap_changed = False
    for entry in roadmap_entries:
        if slug in entry.after:
            entry.after.remove(slug)
            roadmap_changed = True
    if roadmap_changed:
        save_roadmap(cwd, roadmap_entries)

    # Clean icebox
    icebox_entries = load_icebox(cwd)
    icebox_changed = False
    for entry in icebox_entries:
        if slug in entry.after:
            entry.after.remove(slug)
            icebox_changed = True
    if icebox_changed:
        save_icebox(cwd, icebox_entries)


def freeze_to_icebox(cwd: str, slug: str) -> bool:
    """Move a slug from roadmap to icebox (prepended). Returns False if not in roadmap."""
    entries = load_roadmap(cwd)
    entry = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            entry = entries.pop(i)
            break
    if entry is None:
        return False

    save_roadmap(cwd, entries)

    icebox = load_icebox(cwd)
    icebox.insert(0, entry)
    save_icebox(cwd, icebox)

    # Move folder if it exists
    src = Path(cwd) / "todos" / slug
    if src.exists():
        dest_dir = _icebox_dir(cwd)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / slug
        if dest.exists():
            raise FileExistsError(f"Cannot freeze: destination already exists at {dest}")
        shutil.move(str(src), str(dest))

    return True


def unfreeze_from_icebox(cwd: str, slug: str) -> bool:
    """Move a slug from icebox back to roadmap (appended). Returns False if not in icebox."""
    icebox = load_icebox(cwd)
    entry = None
    for i, e in enumerate(icebox):
        if e.slug == slug:
            entry = icebox.pop(i)
            break
    if entry is None:
        return False

    save_icebox(cwd, icebox)

    roadmap = load_roadmap(cwd)
    roadmap.append(entry)
    save_roadmap(cwd, roadmap)

    # Move folder back if it exists in _icebox/
    src = _icebox_dir(cwd) / slug
    if src.exists():
        dest = Path(cwd) / "todos" / slug
        if dest.exists():
            raise FileExistsError(f"Cannot unfreeze: destination already exists at {dest}")
        shutil.move(str(src), str(dest))

    return True


def migrate_icebox_to_subfolder(cwd: str) -> int:
    """One-time migration: move icebox folders from todos/ to todos/_icebox/.

    Idempotent: if todos/icebox.yaml is absent but todos/_icebox/icebox.yaml
    exists, the migration is considered done and 0 is returned.

    Returns count of items moved.
    """
    todos_root = Path(cwd) / "todos"
    old_manifest = todos_root / "icebox.yaml"
    new_dir = todos_root / "_icebox"
    new_manifest = new_dir / "icebox.yaml"

    if not old_manifest.exists():
        # Already migrated (or nothing to migrate)
        return 0

    new_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    raw = yaml.safe_load(old_manifest.read_text()) or []
    if isinstance(raw, list):
        entries = raw

    moved = 0
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug") or item.get("group")
        if not slug:
            continue
        src = todos_root / slug
        dest = new_dir / slug
        if src.exists() and not dest.exists():
            shutil.move(str(src), str(dest))
            moved += 1

    # Relocate manifest
    shutil.move(str(old_manifest), str(new_manifest))
    return moved
