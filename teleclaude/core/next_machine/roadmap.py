"""Legacy filesystem roadmap manifest helpers for characterization tests."""

# pylint: disable=duplicate-code  # Legacy roadmap/icebox YAML helpers intentionally mirror each other.

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import RoadmapDict, RoadmapEntry


def _roadmap_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "roadmap.yaml"


def load_roadmap(cwd: str) -> list[RoadmapEntry]:
    """Load roadmap entries from the legacy YAML manifest."""
    path = _roadmap_path(cwd)
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


def save_roadmap(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write roadmap entries to the legacy YAML manifest."""
    path = _roadmap_path(cwd)
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
