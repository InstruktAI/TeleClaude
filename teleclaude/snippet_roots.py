"""Shared snippet-root discovery helpers."""

from __future__ import annotations

from pathlib import Path


def snippet_files(snippets_root: Path, *, include_baseline: bool) -> list[Path]:
    """List all Markdown snippet files under a root."""
    files = [path for path in snippets_root.rglob("*.md") if path.name != "index.yaml"]
    if include_baseline:
        return files
    return [path for path in files if "baseline" not in path.parts]


def iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    roots: list[Path] = []
    candidates = [
        project_root / "docs" / "global",
        project_root / "docs" / "project",
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
