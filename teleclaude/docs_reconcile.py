"""Reconcile snippet lifecycle frontmatter against todo status."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml

from teleclaude.constants import RoadmapStatus
from teleclaude.snippet_roots import iter_snippet_roots, snippet_files


@dataclass(frozen=True)
class SnippetDeliveredByRewriteResult:
    """A single delivered_by slug rewrite."""

    path: Path
    old_slug: str
    new_slug: str


@dataclass(frozen=True)
class SnippetWriteResult:
    """A planned snippet frontmatter write."""

    path: Path
    rendered_content: str
    removed_slugs: tuple[str, ...]
    write_required: bool


@dataclass(frozen=True)
class BlockingSnippet:
    """Snippet that would lose every live deliverer if a slug is removed."""

    path: str
    slug_role: Literal["sole", "last_live_among_removed"]
    live_deliverer_count: int
    other_removed_deliverers: list[str]


class SnippetFrontmatter(TypedDict, total=False):
    """Snippet frontmatter fields relevant to lifecycle reconciliation."""

    id: str
    type: str
    scope: str
    description: str
    visibility: str
    activation_trigger: str
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


def _is_live_deliverer(slug: str, roadmap_status_map: Mapping[str, str]) -> bool:
    status = roadmap_status_map.get(slug)
    return status is not None and status != RoadmapStatus.REMOVED


_MetadataPlanner = Callable[
    [Path, SnippetFrontmatter, list[str], Mapping[str, str]],
    tuple[SnippetFrontmatter | None, tuple[str, ...]],
]


def scan_remove_orphans(
    project_root: Path,
    candidate_slug: str,
    roadmap_status_map: Mapping[str, str],
) -> list[BlockingSnippet]:
    """Return snippets that would be orphaned by removing ``candidate_slug``."""
    blockers: list[BlockingSnippet] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, _body = parsed
        delivered_by = _delivered_by(metadata)
        if candidate_slug not in delivered_by:
            continue

        live_after_remove = [
            slug for slug in delivered_by if slug != candidate_slug and _is_live_deliverer(slug, roadmap_status_map)
        ]
        if live_after_remove:
            continue

        other_removed = [
            slug
            for slug in delivered_by
            if slug != candidate_slug and roadmap_status_map.get(slug) == RoadmapStatus.REMOVED
        ]
        blockers.append(
            BlockingSnippet(
                path=str(snippet_path),
                slug_role="last_live_among_removed" if other_removed else "sole",
                live_deliverer_count=0,
                other_removed_deliverers=other_removed,
            )
        )
    return blockers


def _purged_metadata_planner(purged_slugs: tuple[str, ...]) -> _MetadataPlanner:
    purged_slug_set = set(purged_slugs)

    def plan(
        snippet_path: Path,
        metadata: SnippetFrontmatter,
        delivered_by: list[str],
        roadmap_status_map: Mapping[str, str],
    ) -> tuple[SnippetFrontmatter | None, tuple[str, ...]]:
        removed_slugs = tuple(slug for slug in delivered_by if slug in purged_slug_set)
        if not removed_slugs:
            return None, ()

        remaining_slugs = [slug for slug in delivered_by if slug not in purged_slug_set]
        live_remaining = [slug for slug in remaining_slugs if _is_live_deliverer(slug, roadmap_status_map)]
        if not live_remaining:
            raise RuntimeError(
                f"Cannot purge snippet lifecycle deliverer(s) {', '.join(removed_slugs)} from {snippet_path}: "
                "zero live deliverers would remain"
            )

        next_metadata = cast(SnippetFrontmatter, dict(metadata))
        next_metadata["delivered_by"] = remaining_slugs
        return next_metadata, removed_slugs

    return plan


def _planned_snippet_writes(
    project_root: Path,
    roadmap_status_map: Mapping[str, str],
    metadata_planner: _MetadataPlanner,
    *,
    only_slug: str | None = None,
) -> list[SnippetWriteResult]:
    results: list[SnippetWriteResult] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, body = parsed
        delivered_by = _delivered_by(metadata)
        if not delivered_by:
            continue
        if only_slug is not None and only_slug not in delivered_by:
            continue
        next_metadata, removed_slugs = metadata_planner(snippet_path, metadata, delivered_by, roadmap_status_map)
        if next_metadata is None:
            continue
        rendered = _render_frontmatter(next_metadata, body)
        results.append(
            SnippetWriteResult(
                path=snippet_path,
                rendered_content=rendered,
                removed_slugs=removed_slugs,
                write_required=rendered != content,
            )
        )
    return results


def reconcile_snippets_for_purged_slugs(
    project_root: Path,
    purged_slugs: Iterable[str],
    roadmap_status_map: Mapping[str, str],
) -> list[SnippetWriteResult]:
    """Plan snippet lifecycle frontmatter rewrites for hard-purged todo slugs."""
    purged_slug_tuple = tuple(dict.fromkeys(purged_slugs))
    if not purged_slug_tuple:
        return []
    return _planned_snippet_writes(project_root, roadmap_status_map, _purged_metadata_planner(purged_slug_tuple))


def rewrite_delivered_by_slug(
    project_root: Path,
    old_slug: str,
    new_slug: str,
) -> list[SnippetDeliveredByRewriteResult]:
    """Rewrite snippet lifecycle delivered_by references from old slug to new slug."""
    results: list[SnippetDeliveredByRewriteResult] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, body = parsed
        delivered_by = _delivered_by(metadata)
        if old_slug not in delivered_by:
            continue

        next_metadata = cast(SnippetFrontmatter, dict(metadata))
        next_metadata["delivered_by"] = list(
            dict.fromkeys(new_slug if slug == old_slug else slug for slug in delivered_by)
        )
        rendered = _render_frontmatter(next_metadata, body)
        if rendered == content:
            continue
        snippet_path.write_text(rendered, encoding="utf-8")
        results.append(SnippetDeliveredByRewriteResult(path=snippet_path, old_slug=old_slug, new_slug=new_slug))
    return results
