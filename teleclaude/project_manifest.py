from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

MANIFEST_PATH = Path("~/.teleclaude/projects.yaml")


@dataclass(frozen=True)
class ProjectManifestEntry:
    name: str
    description: str
    index_path: str
    project_root: str


def _normalize_manifest_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _entry_from_raw(item: object) -> ProjectManifestEntry | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    description = item.get("description")
    index_path = item.get("index_path")
    project_root = item.get("project_root")
    if not isinstance(name, str) or not isinstance(index_path, str) or not isinstance(project_root, str):
        return None
    if not isinstance(description, str):
        description = ""
    return ProjectManifestEntry(
        name=name.strip(),
        description=description.strip(),
        index_path=str(Path(index_path).expanduser().resolve()),
        project_root=str(Path(project_root).expanduser().resolve()),
    )


def _parse_manifest_data(raw_data: object) -> list[ProjectManifestEntry]:
    if isinstance(raw_data, dict):
        raw_entries = raw_data.get("projects")
    elif isinstance(raw_data, list):
        raw_entries = raw_data
    else:
        raw_entries = []
    if not isinstance(raw_entries, list):
        return []

    entries: list[ProjectManifestEntry] = []
    seen_roots: set[str] = set()
    for raw_entry in raw_entries:
        parsed = _entry_from_raw(raw_entry)
        if not parsed or parsed.project_root in seen_roots:
            continue
        seen_roots.add(parsed.project_root)
        entries.append(parsed)
    return entries


def load_manifest(path: Path = MANIFEST_PATH) -> list[ProjectManifestEntry]:
    manifest_path = _normalize_manifest_path(path)
    if not manifest_path.exists():
        return []

    try:
        raw_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = _parse_manifest_data(raw_data)
    live_entries: list[ProjectManifestEntry] = []
    for entry in entries:
        if Path(entry.index_path).exists():
            live_entries.append(entry)
    return live_entries


def register_project(
    path: Path,
    project_root: Path,
    project_name: str,
    description: str,
    index_path: Path,
) -> None:
    manifest_path = _normalize_manifest_path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    entries = load_manifest(manifest_path)
    normalized_root = str(project_root.expanduser().resolve())
    normalized_index = str(index_path.expanduser().resolve())
    normalized_name = project_name.strip()
    normalized_description = description.strip()

    updated = False
    next_entries: list[ProjectManifestEntry] = []
    for entry in entries:
        if entry.project_root == normalized_root:
            next_entries.append(
                ProjectManifestEntry(
                    name=normalized_name,
                    description=normalized_description,
                    index_path=normalized_index,
                    project_root=normalized_root,
                )
            )
            updated = True
            continue
        next_entries.append(entry)

    if not updated:
        next_entries.append(
            ProjectManifestEntry(
                name=normalized_name,
                description=normalized_description,
                index_path=normalized_index,
                project_root=normalized_root,
            )
        )

    next_entries.sort(key=lambda e: e.name.lower())
    payload = {
        "projects": [
            {
                "name": entry.name,
                "description": entry.description,
                "index_path": entry.index_path,
                "project_root": entry.project_root,
            }
            for entry in next_entries
        ]
    }
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
