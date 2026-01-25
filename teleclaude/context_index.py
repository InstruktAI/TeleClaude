"""Build project snippet index artifacts for context selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, NotRequired, TypedDict, cast

import yaml
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")


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


class SnippetIndexEntry(TypedDict):
    id: str
    description: str
    path: str
    requires: NotRequired[list[str]]


class IndexPayload(TypedDict):
    project_root: str
    snippets: list[SnippetIndexEntry]


def _split_frontmatter(raw: str) -> tuple[str, str] | None:
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

    head = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    return head, body


def _read_frontmatter(raw: str, *, path: Path) -> tuple[Frontmatter | None, str]:
    split = _split_frontmatter(raw)
    if split is None:
        return None, raw
    frontmatter_text, body = split
    try:
        data = yaml.safe_load(frontmatter_text)
    except Exception as exc:  # pragma: no cover - logged and skipped
        logger.warning("Failed to parse frontmatter", path=str(path), error=str(exc))
        return None, body

    if not isinstance(data, dict):
        return None, body

    return cast(Frontmatter, data), body


def _resolve_requires(file_path: Path, requires: Iterable[str], project_root: Path) -> list[str]:
    resolved: list[str] = []
    for req in requires:
        candidate = Path(req).expanduser()
        if not candidate.is_absolute():
            absolute = (file_path.parent / candidate).resolve()
        else:
            absolute = candidate.resolve()
        try:
            resolved.append(str(absolute.relative_to(project_root)))
        except ValueError:
            resolved.append(str(absolute))
    return resolved


def _extract_required_reads(content: str) -> list[str]:
    lines = content.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            header_idx = idx
            break
    if header_idx is None:
        return []
    section_start = header_idx + 1
    section_end = next(
        (i for i in range(section_start, len(lines)) if _HEADER_LINE.match(lines[i])),
        len(lines),
    )
    refs: list[str] = []
    for line in lines[section_start:section_end]:
        match = _REQUIRED_READ_LINE.match(line)
        if match:
            refs.append(match.group(1))
    return refs


def build_snippet_index(project_root: Path, *, snippets_dir: Path | None = None) -> list[SnippetEntry]:
    """Build snippet index entries from a project's docs/ directory."""
    root = project_root.resolve()
    snippets_root = (snippets_dir or (root / "docs")).resolve()
    if not snippets_root.exists():
        logger.warning("Snippets directory missing", path=str(snippets_root))
        return []

    for index_path in sorted(snippets_root.rglob("index.md")):
        if "baseline" in index_path.parts:
            continue
        try:
            index_path.unlink()
            logger.warning("index_removed", path=str(index_path))
        except Exception as exc:
            logger.warning("index_remove_failed", path=str(index_path), error=str(exc))

    entries: list[SnippetEntry] = []
    for file_path in sorted(snippets_root.rglob("*.md")):
        if "baseline" in str(file_path):
            continue
        raw = file_path.read_text(encoding="utf-8")
        metadata, body = _read_frontmatter(raw, path=file_path)
        if not metadata:
            continue
        snippet_id = metadata.get("id")
        description = metadata.get("description")
        if not isinstance(snippet_id, str) or not isinstance(description, str):
            continue
        requires_list = _extract_required_reads(body)
        requires = _resolve_requires(file_path, requires_list, root)
        try:
            relative_path = str(file_path.relative_to(root))
        except ValueError:
            relative_path = str(file_path)
        entry = SnippetEntry(
            snippet_id=snippet_id,
            description=description,
            path=relative_path,
            requires=requires,
        )
        entries.append(entry)

    entries.sort(key=lambda entry: entry.snippet_id)
    return entries


def build_index_payload(project_root: Path) -> IndexPayload:
    """Build the YAML payload for docs/index.yaml."""
    entries = build_snippet_index(project_root)
    snippets_payload: list[SnippetIndexEntry] = []
    for entry in entries:
        item: SnippetIndexEntry = {
            "id": entry.snippet_id,
            "description": entry.description,
            "path": entry.path,
        }
        if entry.requires:
            item["requires"] = entry.requires
        snippets_payload.append(item)
    payload: IndexPayload = {
        "project_root": str(project_root.resolve()),
        "snippets": snippets_payload,
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
