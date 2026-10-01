"""Shared snippet-root discovery helpers."""

from __future__ import annotations

from pathlib import Path

from teleclaude.capabilities import PermissionSurface, resolve_tier_permissions
from teleclaude.config.loader import list_company_config_paths
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import ConfigFileName
from teleclaude.snippet_validation import is_generated_domain_artifact_source


def is_excluded_snippet_path(path: Path, snippets_root: Path) -> bool:
    """Skip support fragments and directories whose name starts with ``_``."""
    try:
        rel = path.relative_to(snippets_root)
    except ValueError:
        return False
    if rel.parts and rel.parts[0] == "snippets":
        return True
    return any(part.startswith("_") for part in rel.parent.parts)


def snippet_files(snippets_root: Path, *, include_baseline: bool) -> list[Path]:
    """List all Markdown snippet files under a root."""
    files = [
        path
        for path in snippets_root.rglob("*.md")
        if not is_generated_domain_artifact_source(path) and not is_excluded_snippet_path(path, snippets_root)
    ]
    if include_baseline:
        return files
    return [path for path in files if "baseline" not in path.parts]


def iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    roots: list[Path] = []
    candidates = [
        project_root / "docs" / "global",
        project_root / "docs" / "local",
        project_root / "agents" / "docs",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            rel_path = candidate.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        if snippet_files(candidate, include_baseline=include_baseline):
            roots.append(candidate)
    return roots


def iter_declared_tier_roots(home: Path) -> list[tuple[Path, ConfigKind]]:
    """Enumerate every declared company and person tier under ``home``.

    ``home`` is the platform home explicitly — production callers pass the
    runtime home, so tier roots are never bound at import. A candidate is a
    folder holding a tier declaration (a ``teleclaude.yml`` naming the tier);
    an undeclared tier-shaped folder is skipped rather than raising. Companies
    come first, then persons in slug order.
    """
    roots: list[tuple[Path, ConfigKind]] = [
        (config_path.parent, ConfigKind.COMPANY) for config_path in list_company_config_paths(home / "companies")
    ]
    people_root = home / "people"
    if people_root.exists():
        roots.extend(
            (config_path.parent, ConfigKind.PERSON)
            for config_path in sorted(people_root.glob(f"*/{ConfigFileName.OVERLAY}"))
        )
    return roots


def iter_tier_snippet_roots(home: Path) -> list[tuple[Path, ConfigKind]]:
    """Enumerate declared, documentation-participating company and person tiers.

    Filters ``iter_declared_tier_roots`` by the published participation query:
    a declared tier that does not participate contributes no root.
    """
    return [
        (root, kind)
        for root, kind in iter_declared_tier_roots(home)
        if resolve_tier_permissions(root).participates_in(PermissionSurface.DOCUMENTATION)
    ]
