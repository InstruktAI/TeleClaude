"""Reconcile snippet lifecycle frontmatter against roadmap status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import yaml

from teleclaude.resource_validation._snippet import ROADMAP_STATUS_DELIVERED
from teleclaude.snippet_roots import iter_snippet_roots, snippet_files


@dataclass(frozen=True)
class SnippetStatusReconcileResult:
    """A single snippet frontmatter rewrite performed by reconciliation."""

    path: Path
    removed_slugs: tuple[str, ...]


class SnippetFrontmatter(TypedDict, total=False):
    """Snippet frontmatter fields relevant to lifecycle reconciliation."""

    id: str
    type: str
    scope: str
    description: str
    visibility: str
    activation_trigger: str
    applies_to: str
    status: str
    delivered_by: list[str]


def _split_frontmatter(content: str) -> tuple[SnippetFrontmatter, str] | None:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None
    raw_frontmatter = "".join(lines[1:end_idx])
    loaded = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(loaded, dict):
        return None
    body = "".join(lines[end_idx + 1 :])
    return cast(SnippetFrontmatter, loaded), body


def _render_frontmatter(metadata: SnippetFrontmatter, body: str) -> str:
    rendered = yaml.safe_dump(dict(metadata), sort_keys=False, allow_unicode=True)
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    return f"---\n{rendered}---\n{body}"


def _iter_snippet_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for snippets_root in iter_snippet_roots(project_root):
        try:
            rel_path = snippets_root.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        files.extend(snippet_files(snippets_root, include_baseline=include_baseline))
    return sorted(files)


def _delivered_by(metadata: SnippetFrontmatter) -> list[str]:
    raw_metadata = cast(Mapping[str, object], metadata)
    raw_delivered_by = raw_metadata.get("delivered_by")
    if not isinstance(raw_delivered_by, list):
        return []
    if not all(isinstance(slug, str) for slug in raw_delivered_by):
        return []
    return list(raw_delivered_by)


def _reconciled_metadata(
    metadata: SnippetFrontmatter,
    delivered_by: list[str],
    roadmap_status_map: Mapping[str, str],
) -> tuple[SnippetFrontmatter | None, tuple[str, ...]]:
    delivered_slugs = tuple(slug for slug in delivered_by if roadmap_status_map.get(slug) == ROADMAP_STATUS_DELIVERED)
    if not delivered_slugs:
        return None, ()
    next_metadata = cast(SnippetFrontmatter, dict(metadata))
    if len(delivered_slugs) == len(delivered_by):
        next_metadata.pop("status", None)
        next_metadata.pop("delivered_by", None)
        return next_metadata, delivered_slugs
    remaining_slugs = [slug for slug in delivered_by if slug not in delivered_slugs]
    next_metadata["delivered_by"] = remaining_slugs
    return next_metadata, delivered_slugs


def reconcile_snippet_status(
    project_root: Path,
    roadmap_status_map: Mapping[str, str],
) -> list[SnippetStatusReconcileResult]:
    """Remove delivered slugs from snippet lifecycle frontmatter."""
    results: list[SnippetStatusReconcileResult] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, body = parsed
        delivered_by = _delivered_by(metadata)
        if not delivered_by:
            continue
        next_metadata, removed_slugs = _reconciled_metadata(metadata, delivered_by, roadmap_status_map)
        if next_metadata is None:
            continue
        rendered = _render_frontmatter(next_metadata, body)
        if rendered == content:
            continue
        snippet_path.write_text(rendered, encoding="utf-8")
        results.append(SnippetStatusReconcileResult(path=snippet_path, removed_slugs=removed_slugs))
    return results
