"""Shared manifest load/save helpers for roadmap-like YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import RoadmapDict, RoadmapEntry
from teleclaude.core.next_machine.state_io import read_text_sync, write_text_sync


def load_manifest_entries(path: Path) -> list[RoadmapEntry]:
    """Load roadmap-style entries from ``path``."""
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


def save_manifest_entries(path: Path, entries: list[RoadmapEntry], header: str) -> None:
    """Write roadmap-style entries to ``path`` with ``header``."""
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

    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)
