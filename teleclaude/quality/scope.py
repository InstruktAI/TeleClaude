"""Shared scope utilities for quality tooling.

Worktree detection, session scope resolution, project root resolution,
language detection, and path validation used by both lint and test runners.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import yaml

from teleclaude.git import GitCommandError, Repo
from teleclaude.session_identity import get_session_id  # deferred: heavy transitive imports
from teleclaude.todo_scaffold import _collect_session_touched_files  # deferred: heavy transitive imports

logger = logging.getLogger(__name__)

_PYTHON_EXTENSIONS = (".py", ".pyi")
_TYPESCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_PRETTIER_EXTENSIONS = (
    ".md",
    ".mdx",
    ".yaml",
    ".yml",
    ".json",
    ".jsonc",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)


def is_worktree(project_root: Path) -> bool:
    """Check if the project is in a git worktree (not the main repo).

    Compares git rev-parse --git-common-dir vs --git-dir. In a worktree
    these differ; in the main repo they are identical.

    Justified subprocess: git plumbing has no Python API.
    """
    try:
        git_common = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return git_common != git_dir
    except subprocess.CalledProcessError:
        return False


def resolve_session_scope(project_root: Path) -> list[str]:
    """Resolve files touched by the current agent session for scoped operations.

    Wraps session_identity.get_session_id and todo_scaffold._collect_session_touched_files.
    Raises RuntimeError when no session identity exists or collection fails.
    """
    session_id = get_session_id()
    if not session_id:
        raise RuntimeError("No active session identity")

    try:
        touched: set[str] = _collect_session_touched_files(str(project_root))
    except Exception as exc:
        raise RuntimeError(f"Failed to collect session-touched files: {exc}") from exc

    # Filter to files that exist on disk — session transcripts may reference
    # example paths from docstrings that aren't real files.
    existing = [f for f in sorted(touched) if (project_root / f).exists()]

    # Intersect with git-dirty files — only include files that are actually
    # modified or untracked. Touched files that were already committed or
    # reverted are not actionable.
    try:
        repo = Repo(str(project_root))
        status = repo.git.status("--porcelain")
        dirty = set()
        for line in status.splitlines():
            if len(line) > 3:
                dirty.add(line[3:].strip())
        if dirty:
            existing = [f for f in existing if f in dirty]
    except (GitCommandError, Exception):
        pass  # If git fails, return all existing files as fallback

    return existing


def resolve_project_root(cwd: Path) -> Path:
    """Walk up from cwd to find the nearest project directory containing teleclaude.yml.

    Hidden directories (name starts with ``'.'``) are skipped — they contain
    system configuration, not project roots.
    """
    current = cwd.resolve()
    while True:
        if not current.name.startswith(".") and (current / "teleclaude.yml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("No teleclaude.yml found in directory hierarchy")
        current = parent


def get_project_languages(project_root: Path) -> list[str]:
    """Read languages from teleclaude.yml. Falls back to singular language field."""
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return []
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return []
    languages = data.get("languages", [])
    if languages:
        return [str(lang) for lang in languages]
    lang = data.get("language")
    if lang is not None:
        return [str(lang)]
    return []


def get_project_language(project_root: Path) -> str | None:
    """Read the language field from teleclaude.yml. Returns None if absent.

    Deprecated: use get_project_languages() for multi-language support.
    """
    languages = get_project_languages(project_root)
    return languages[0] if languages else None


def python_files(paths: list[str]) -> list[str]:
    """Return only Python targets from *paths*.

    Directories are passed through unchanged — ruff and pyright recurse into
    them. Only individual file paths are filtered by extension.
    """
    return [path for path in paths if Path(path).is_dir() or path.endswith(_PYTHON_EXTENSIONS)]


def typescript_files(paths: list[str]) -> list[str]:
    """Return only JavaScript/TypeScript targets from *paths*."""
    return [path for path in paths if path.endswith(_TYPESCRIPT_EXTENSIONS)]


def prettier_files(paths: list[str]) -> list[str]:
    """Return only files owned by prettier from *paths*."""
    return [path for path in paths if path.endswith(_PRETTIER_EXTENSIONS)]


def validate_scoped_paths(paths: list[str], project_root: Path) -> list[str]:
    """Filter out paths with traversal sequences or absolute paths outside project_root.

    Security boundary: prevents path injection via crafted transcript data.
    """
    safe: list[str] = []
    project_root_str = str(project_root.resolve())
    for p in paths:
        if ".." in p:
            logger.warning("Rejected traversal path from session scope: %s", p)
            continue
        if p.startswith("/") and not p.startswith(project_root_str):
            logger.warning("Rejected absolute path outside project root: %s", p)
            continue
        safe.append(p)
    return safe
