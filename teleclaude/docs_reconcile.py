"""Reconcile snippet lifecycle frontmatter against todo status."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
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


class ReconciliationMode(StrEnum):
    """Closed lifecycle transformations supported by snippet reconciliation."""

    DELIVER = "deliver"
    ABANDON = "abandon"
    RENAME = "rename"
    RESTORE = "restore"


class ReconciliationCarrier(StrEnum):
    """The persisted carrier whose lifecycle identity is being reconciled."""

    PLANNED = "planned"
    PLANNED_CHANGE = "planned_change"
    DELIVERED_BY = "delivered_by"
    COMPANION = "companion"


@dataclass(frozen=True)
class ReconciliationFault(RuntimeError):
    """A structural documentation fault that prevents an unsafe lifecycle move."""

    slug: str
    relative_path: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.slug}: {self.relative_path}:{self.line}: {self.reason}"


@dataclass(frozen=True)
class ReconciliationWrite:
    """An exact source-to-rendered mutation in a complete reconciliation plan."""

    path: Path
    relative_path: str
    original_content: str | None
    rendered_content: str | None
    line: int
    carrier: ReconciliationCarrier
    reason: str


@dataclass(frozen=True)
class ReconciliationPlan:
    """A fully preflighted, all-or-nothing documentation reconciliation plan."""

    slug: str
    mode: ReconciliationMode
    writes: tuple[ReconciliationWrite, ...]

    @property
    def changed_paths(self) -> tuple[Path, ...]:
        """Return every path that application may create, update, or remove."""
        return tuple(write.path for write in self.writes)


def reverse_reconciliation_plan(plan: ReconciliationPlan) -> ReconciliationPlan:
    """Return the exact inverse of an already-applied reconciliation plan."""
    return ReconciliationPlan(
        slug=plan.slug,
        mode=ReconciliationMode.RESTORE,
        writes=tuple(
            ReconciliationWrite(
                path=write.path,
                relative_path=write.relative_path,
                original_content=write.rendered_content,
                rendered_content=write.original_content,
                line=write.line,
                carrier=write.carrier,
                reason="restore reverses lifecycle reconciliation",
            )
            for write in plan.writes
        ),
    )


@dataclass(frozen=True)
class MarkerDivergence:
    """A settled lifecycle identity still represented by live documentation material."""

    slug: str
    relative_path: str
    line: int
    carrier: ReconciliationCarrier
    reason: str


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


def _relative_path(project_root: Path, path: Path) -> str:
    """Return the repository-relative form required in reconciliation evidence."""
    return str(path.relative_to(project_root))


def _first_line(content: str, slug: str) -> int:
    """Return the first line carrying a slug, defaulting to the start of the file."""
    for line, value in enumerate(content.splitlines(), start=1):
        if slug in value:
            return line
    return 1


def _carrier_for_change(content: str, slug: str) -> ReconciliationCarrier:
    """Classify the first mechanical lifecycle carrier present in ``content``."""
    if f"planned-change:{slug}" in content:
        return ReconciliationCarrier.PLANNED_CHANGE
    if f"planned:{slug}" in content:
        return ReconciliationCarrier.PLANNED
    return ReconciliationCarrier.DELIVERED_BY


def _replace_marker_slug(content: str, old_slug: str, new_slug: str) -> str:
    """Rename a closed marker token while leaving ordinary prose untouched."""
    token = re.compile(
        rf"(?P<prefix><!--[ \t]*/?(?:planned-change|planned|change):){re.escape(old_slug)}(?P<suffix>[ \t]*-->)"
    )
    return token.sub(rf"\g<prefix>{new_slug}\g<suffix>", content)


def _rewrite_delivered_by_content(content: str, old_slug: str, new_slug: str | None) -> str:
    """Replace or clear one lifecycle owner in parsed frontmatter."""
    parsed = _split_frontmatter(content)
    if parsed is None:
        return content
    metadata, body = parsed
    delivered_by = _delivered_by(metadata)
    if old_slug not in delivered_by:
        return content
    next_metadata = cast(SnippetFrontmatter, dict(metadata))
    remaining = [slug for slug in delivered_by if slug != old_slug]
    if new_slug is not None:
        remaining.append(new_slug)
    if remaining:
        next_metadata["delivered_by"] = list(dict.fromkeys(remaining))
    else:
        next_metadata.pop("delivered_by", None)
    return _render_frontmatter(next_metadata, body)


def _render_mode(content: str, slug: str, mode: ReconciliationMode, new_slug: str | None) -> str:
    """Render the mechanical carrier transformation for one source document."""
    if mode is ReconciliationMode.DELIVER:
        resolved = resolve_planned_change_for_delivery(content, slug)
        return _rewrite_delivered_by_content(strip_planned_markers(resolved, slug), slug, None)
    if mode is ReconciliationMode.ABANDON:
        resolved = resolve_planned_change_for_abandon(content, slug)
        return _rewrite_delivered_by_content(drop_planned_additions(resolved, slug), slug, None)
    if mode is ReconciliationMode.RENAME and new_slug is not None:
        rewritten = _replace_marker_slug(content, slug, new_slug)
        return _rewrite_delivered_by_content(rewritten, slug, new_slug)
    return content


def plan_snippet_reconciliation(
    project_root: Path,
    slug: str,
    mode: ReconciliationMode,
    *,
    new_slug: str | None = None,
) -> ReconciliationPlan:
    """Preflight every lifecycle carrier before any reconciliation source is written."""
    if mode is ReconciliationMode.RENAME and new_slug is None:
        raise ReconciliationFault(slug, "", 0, "rename requires a destination slug")
    files = _iter_snippet_files(project_root)
    contents = {path: path.read_text(encoding="utf-8") for path in files}
    companion_writes: dict[Path, ReconciliationWrite] = {}
    for path in files:
        if companion_slug(path) != slug:
            continue
        parent = companion_parent(path)
        if parent is None:
            raise ReconciliationFault(slug, _relative_path(project_root, path), 1, "orphan companion")
        destination = parent
        if mode is ReconciliationMode.RENAME and new_slug is not None:
            destination = parent.with_name(f"{parent.stem}.{new_slug}.md")
            if destination.exists() and destination != path:
                raise ReconciliationFault(
                    slug, _relative_path(project_root, destination), 1, "companion destination exists"
                )
        if mode is ReconciliationMode.DELIVER:
            contents[parent] = contents[path]
            contents.pop(path, None)
            companion_writes[path] = ReconciliationWrite(
                path=path,
                relative_path=_relative_path(project_root, path),
                original_content=contents.get(path, path.read_text(encoding="utf-8")),
                rendered_content=None,
                line=1,
                carrier=ReconciliationCarrier.COMPANION,
                reason="delivery replaces parent with companion",
            )
        elif mode is ReconciliationMode.RENAME and new_slug is not None:
            contents[destination] = contents.pop(path)
            companion_writes[path] = ReconciliationWrite(
                path=path,
                relative_path=_relative_path(project_root, path),
                original_content=path.read_text(encoding="utf-8"),
                rendered_content=None,
                line=1,
                carrier=ReconciliationCarrier.COMPANION,
                reason="rename moves companion identity",
            )
        elif mode is ReconciliationMode.ABANDON:
            contents.pop(path, None)
            companion_writes[path] = ReconciliationWrite(
                path=path,
                relative_path=_relative_path(project_root, path),
                original_content=path.read_text(encoding="utf-8"),
                rendered_content=None,
                line=1,
                carrier=ReconciliationCarrier.COMPANION,
                reason="abandon removes undelivered companion",
            )
    writes: list[ReconciliationWrite] = list(companion_writes.values())
    for path, original in contents.items():
        rendered = _render_mode(original, slug, mode, new_slug)
        if rendered == original:
            continue
        writes.append(
            ReconciliationWrite(
                path=path,
                relative_path=_relative_path(project_root, path),
                original_content=path.read_text(encoding="utf-8") if path.exists() else None,
                rendered_content=rendered,
                line=_first_line(original, slug),
                carrier=_carrier_for_change(original, slug),
                reason=f"{mode.value} reconciles lifecycle carrier",
            )
        )
    return ReconciliationPlan(slug=slug, mode=mode, writes=tuple(writes))


def apply_reconciliation_plan(plan: ReconciliationPlan) -> None:
    """Apply a preflighted plan, restoring already-written sources if a write fails."""
    applied: list[ReconciliationWrite] = []
    try:
        for write in plan.writes:
            current = write.path.read_text(encoding="utf-8") if write.path.exists() else None
            if current != write.original_content:
                raise ReconciliationFault(plan.slug, write.relative_path, write.line, "source changed after preflight")
            if write.rendered_content is None:
                write.path.unlink(missing_ok=True)
            else:
                write.path.parent.mkdir(parents=True, exist_ok=True)
                write.path.write_text(write.rendered_content, encoding="utf-8")
            applied.append(write)
    except OSError as exc:
        restore_reconciliation_plan(ReconciliationPlan(plan.slug, ReconciliationMode.RESTORE, tuple(applied)))
        raise ReconciliationFault(plan.slug, "", 0, str(exc)) from exc


def restore_reconciliation_plan(plan: ReconciliationPlan) -> None:
    """Restore the exact preflight source bytes for every write in reverse order."""
    for write in reversed(plan.writes):
        if write.original_content is None:
            write.path.unlink(missing_ok=True)
        else:
            write.path.parent.mkdir(parents=True, exist_ok=True)
            write.path.write_text(write.original_content, encoding="utf-8")


def find_marker_divergence(
    project_root: Path,
    todo_status_map: Mapping[str, str],
) -> list[MarkerDivergence]:
    """Report settled slugs still represented by mechanical lifecycle carriers."""
    settled = {TodoStatus.DELIVERED, TodoStatus.REMOVED, TodoStatus.HOLDER}
    findings: list[MarkerDivergence] = []
    for path in _iter_snippet_files(project_root):
        content = path.read_text(encoding="utf-8")
        for slug, status in todo_status_map.items():
            if status not in settled:
                continue
            carrier = _carrier_for_change(content, slug)
            carries_marker = f"planned:{slug}" in content or f"planned-change:{slug}" in content
            carries_owner = (
                slug in _delivered_by(_split_frontmatter(content)[0]) if _split_frontmatter(content) else False
            )
            carries_companion = companion_slug(path) == slug
            if not (carries_marker or carries_owner or carries_companion):
                continue
            findings.append(
                MarkerDivergence(
                    slug=slug,
                    relative_path=_relative_path(project_root, path),
                    line=_first_line(content, slug),
                    carrier=ReconciliationCarrier.COMPANION if carries_companion else carrier,
                    reason="settled todo retains pending documentation material",
                )
            )
    return findings


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


class ResidualMarkerError(RuntimeError):
    """A delivered slug's in-body markers survived the reconcile fold.

    With validation rejecting inline and nested markers upstream this never fires
    in practice; it exists so a future fold gap fails loudly at delivery — naming
    the file, line, and slug — instead of silently leaving a stale marker that
    jams the platform-wide liveness gate.
    """


def assert_no_residual_markers(project_root: Path, slug: str) -> None:
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
