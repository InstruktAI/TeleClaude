"""Build project snippet index artifacts for context selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypedDict, cast

import yaml
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SnippetEntry:
    """Single snippet entry for index artifacts."""

    snippet_id: str
    description: str
    path: str
    requires: list[str]


class Frontmatter(TypedDict, total=False):
    id: str
    description: str
    requires: list[str]


class SnippetIndexEntry(TypedDict):
    id: str
    description: str
    path: str
    requires: list[str]


class IndexPayload(TypedDict):
    project_root: str
    snippets: list[SnippetIndexEntry]


def _read_frontmatter(path: Path) -> Frontmatter | None:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return None

    lines = raw.splitlines()
    if len(lines) < 3:
        return None

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return None

    frontmatter_text = "\n".join(lines[1:end_index])
    try:
        data = yaml.safe_load(frontmatter_text)
    except Exception as exc:  # pragma: no cover - logged and skipped
        logger.warning("Failed to parse frontmatter", path=str(path), error=str(exc))
        return None

    if not isinstance(data, dict):
        return None

    return cast(Frontmatter, data)


def _resolve_requires(file_path: Path, requires: Iterable[str], project_root: Path) -> list[str]:
    resolved: list[str] = []
    for req in requires:
        absolute = (file_path.parent / req).resolve()
        try:
            resolved.append(str(absolute.relative_to(project_root)))
        except ValueError:
            resolved.append(str(absolute))
    return resolved


def build_snippet_index(project_root: Path, *, snippets_dir: Path | None = None) -> list[SnippetEntry]:
    """Build snippet index entries from a project's docs/snippets directory."""
    root = project_root.resolve()
    snippets_root = (snippets_dir or (root / "docs" / "snippets")).resolve()
    if not snippets_root.exists():
        logger.warning("Snippets directory missing", path=str(snippets_root))
        return []

    entries: list[SnippetEntry] = []
    for file_path in sorted(snippets_root.rglob("*.md")):
        if "baseline" in str(file_path):
            continue
        metadata = _read_frontmatter(file_path)
        if not metadata:
            continue
        snippet_id = metadata.get("id")
        description = metadata.get("description")
        if not isinstance(snippet_id, str) or not isinstance(description, str):
            continue
        requires_list = metadata.get("requires", [])
        requires = _resolve_requires(file_path, requires_list, root)
        try:
            relative_path = str(file_path.relative_to(root))
        except ValueError:
            relative_path = str(file_path)
        entries.append(
            SnippetEntry(
                snippet_id=snippet_id,
                description=description,
                path=relative_path,
                requires=requires,
            )
        )

    entries.sort(key=lambda entry: entry.snippet_id)
    return entries


def build_index_payload(project_root: Path) -> IndexPayload:
    """Build the YAML payload for docs/index.yaml."""
    entries = build_snippet_index(project_root)
    payload: IndexPayload = {
        "project_root": str(project_root.resolve()),
        "snippets": [
            {
                "id": entry.snippet_id,
                "description": entry.description,
                "path": entry.path,
                "requires": entry.requires,
            }
            for entry in entries
        ],
    }
    return payload


def write_index_yaml(project_root: Path, output_path: Path | None = None) -> Path:
    """Write the snippet index YAML to docs/index.yaml (default)."""
    target = output_path or (project_root / "docs" / "index.yaml")
    payload = build_index_payload(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)
    return target
