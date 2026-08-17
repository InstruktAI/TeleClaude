"""Reconcile snippet lifecycle frontmatter against todo status."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

import yaml

from teleclaude.constants import TodoStatus
from teleclaude.doc_body import (
    drop_planned_additions,
    resolve_planned_change_for_abandon,
    resolve_planned_change_for_delivery,
    strip_planned_markers,
)
from teleclaude.snippet_roots import iter_snippet_roots, snippet_files
from teleclaude.snippet_validation import companion_parent, companion_slug


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
class SnippetMarkerCleanupPlan:
    """An exact-source rewrite that abandons one slug's pending markers."""

    path: Path
    original_content: str
    cleaned_content: str


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


def _is_live_deliverer(slug: str, todo_status_map: Mapping[str, str]) -> bool:
    status = todo_status_map.get(slug)
    return status is not None and status != TodoStatus.REMOVED


def scan_remove_orphans(
    project_root: Path,
    candidate_slug: str,
    todo_status_map: Mapping[str, str],
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
            slug for slug in delivered_by if slug != candidate_slug and _is_live_deliverer(slug, todo_status_map)
        ]
        if live_after_remove:
            continue

        other_removed = [
            slug for slug in delivered_by if slug != candidate_slug and todo_status_map.get(slug) == TodoStatus.REMOVED
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


def plan_marker_cleanup_for_removed_slug(project_root: Path, slug: str) -> list[SnippetMarkerCleanupPlan]:
    """Plan byte-preserving abandonment of one removed slug's in-body markers."""
    plans: list[SnippetMarkerCleanupPlan] = []
    for snippet_path in _iter_snippet_files(project_root):
        original_content = snippet_path.read_text(encoding="utf-8")
        cleaned_content = drop_planned_additions(original_content, slug)
        cleaned_content = resolve_planned_change_for_abandon(cleaned_content, slug)
        if cleaned_content == original_content:
            continue
        plans.append(
            SnippetMarkerCleanupPlan(
                path=snippet_path,
                original_content=original_content,
                cleaned_content=cleaned_content,
            )
        )
    return plans


def reconcile_snippets_for_purged_slugs(
    project_root: Path,
    purged_slugs: Iterable[str],
    todo_status_map: Mapping[str, str],
) -> list[SnippetWriteResult]:
    """Plan snippet rewrites that retire a hard-purged todo's pending material.

    For each purged slug this clears it from ``delivered_by`` frontmatter and folds
    its in-body markers with *abandon* semantics — the work was never delivered, so a
    ``planned`` ADD block drops with its content and a ``planned-change`` block reverts
    to its original side. A snippet is rewritten when either surface changes. Clearing
    a ``delivered_by`` slug that would leave the snippet with no live deliverer is
    refused: that case is already blocked at soft-remove, so reaching it signals a
    contract breach rather than routine cleanup.
    """
    purged = tuple(dict.fromkeys(purged_slugs))
    if not purged:
        return []
    purged_set = set(purged)
    results: list[SnippetWriteResult] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, body = parsed

        delivered_by = _delivered_by(metadata)
        removed_slugs = tuple(slug for slug in delivered_by if slug in purged_set)
        next_metadata = metadata
        if removed_slugs:
            remaining = [slug for slug in delivered_by if slug not in purged_set]
            live_remaining = [slug for slug in remaining if _is_live_deliverer(slug, todo_status_map)]
            if not live_remaining:
                raise RuntimeError(
                    f"Cannot purge snippet lifecycle deliverer(s) {', '.join(removed_slugs)} from {snippet_path}: "
                    "zero live deliverers would remain"
                )
            next_metadata = cast(SnippetFrontmatter, dict(metadata))
            next_metadata["delivered_by"] = remaining

        next_body = body
        for slug in purged:
            next_body = drop_planned_additions(next_body, slug)
            next_body = resolve_planned_change_for_abandon(next_body, slug)

        if next_metadata is metadata and next_body == body:
            continue
        rendered = _render_frontmatter(next_metadata, next_body)
        results.append(
            SnippetWriteResult(
                path=snippet_path,
                rendered_content=rendered,
                removed_slugs=removed_slugs,
                write_required=rendered != content,
            )
        )
    return results


def _companion_parent(path: Path, slug: str) -> Path | None:
    """If ``path`` is the ``slug``'s companion ``<stem>.<slug>.md``, return its ``<stem>.md``."""
    if companion_slug(path) != slug:
        return None
    return companion_parent(path)


def _clear_delivered_slug(content: str, slug: str) -> str:
    """Strip ``slug`` from a snippet's ``delivered_by`` frontmatter, dropping an empty key."""
    parsed = _split_frontmatter(content)
    if parsed is None:
        return content
    metadata, body = parsed
    delivered_by = _delivered_by(metadata)
    if slug not in delivered_by:
        return content
    remaining = [existing for existing in delivered_by if existing != slug]
    next_metadata = cast(SnippetFrontmatter, dict(metadata))
    if remaining:
        next_metadata["delivered_by"] = remaining
    else:
        next_metadata.pop("delivered_by", None)
    return _render_frontmatter(next_metadata, body)


def reconcile_delivered_snippets(project_root: Path, slug: str) -> list[Path]:
    """Fold a delivered slug's pending doc state into the live contract.

    On delivery the slug's pending material becomes live, so this:
    - replaces each parent ``<stem>.md`` with its companion ``<stem>.<slug>.md`` and
      deletes the companion,
    - replaces the slug's ``<!-- planned-change:slug -->`` block with its replacement body,
    - removes the slug's ``<!-- planned:slug -->`` marker lines, keeping their content,
    - drops the slug from any ``delivered_by`` frontmatter (the snippet is now live).

    Idempotent: a second run finds no companions, markers, or memberships to change.
    Returns the changed and removed paths.
    """
    changed: list[Path] = []

    # 1. Swap companions into their parents first, so later passes see the live body.
    for path in _iter_snippet_files(project_root):
        parent = _companion_parent(path, slug)
        if parent is None:
            continue
        parent.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        changed.extend((parent, path))

    # 2. Strip planned markers and clear delivered_by from the now-live snippets.
    for path in _iter_snippet_files(project_root):
        original = path.read_text(encoding="utf-8")
        resolved = resolve_planned_change_for_delivery(original, slug)
        updated = _clear_delivered_slug(strip_planned_markers(resolved, slug), slug)
        if updated == original:
            continue
        path.write_text(updated, encoding="utf-8")
        if path not in changed:
            changed.append(path)

    _assert_no_residual_markers(project_root, slug)
    return changed


class ResidualMarkerError(RuntimeError):
    """A delivered slug's in-body markers survived the reconcile fold.

    With validation rejecting inline and nested markers upstream this never fires
    in practice; it exists so a future fold gap fails loudly at delivery — naming
    the file, line, and slug — instead of silently leaving a stale marker that
    jams the platform-wide liveness gate.
    """


def _assert_no_residual_markers(project_root: Path, slug: str) -> None:
    pattern = re.compile(rf"<!--[ \t]*/?(?:planned-change|planned|change):{re.escape(slug)}[ \t]*-->")
    for path in _iter_snippet_files(project_root):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                raise ResidualMarkerError(
                    f"reconcile left an unresolved '{slug}' marker after delivery in {path}:{lineno}: {line.strip()}"
                )


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
