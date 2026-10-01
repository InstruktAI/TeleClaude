"""Shared snippet-root discovery helpers."""

from __future__ import annotations

from pathlib import Path

from teleclaude.capabilities import PermissionSurface, resolve_tier_permissions
from teleclaude.config.loader import list_company_config_paths
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import ConfigFileName


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
        if path.name not in ("index.yaml", "domain-baseline-bundle.md")
        and not is_excluded_snippet_path(path, snippets_root)
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


def iter_tier_snippet_roots(home: Path) -> list[tuple[Path, ConfigKind]]:
    """Enumerate declared, documentation-participating company and person tiers.

    ``home`` is the platform home explicitly — production callers pass the
    runtime home, so tier roots are never bound at import. Discovers candidates
    by the presence of a tier declaration (a ``teleclaude.yml`` naming the tier)
    under ``home``, then filters by the published participation query — an
    undeclared tier-shaped folder is skipped rather than raising, and a declared
    tier that does not participate contributes no root.
    """
    roots: list[tuple[Path, ConfigKind]] = []
    for config_path in list_company_config_paths(home / "companies"):
        root = config_path.parent
        if resolve_tier_permissions(root).participates_in(PermissionSurface.DOCUMENTATION):
            roots.append((root, ConfigKind.COMPANY))
    people_root = home / "people"
    if people_root.exists():
        for config_path in sorted(people_root.glob(f"*/{ConfigFileName.OVERLAY}")):
            root = config_path.parent
            if resolve_tier_permissions(root).participates_in(PermissionSurface.DOCUMENTATION):
                roots.append((root, ConfigKind.PERSON))
    return roots
