"""Shared scope utilities for quality tooling.

Workspace scope resolution, language detection, and path validation used by
code, lint, and test commands.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from teleclaude.git import GitCommandError, Repo
from teleclaude.session_identity import get_session_id  # deferred: heavy transitive imports
from teleclaude.todo_scaffold import collect_session_touched_files  # deferred: heavy transitive imports

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


class WorkspaceScopeKind(Enum):
    WORKTREE = "worktree"
    SHARED_BRANCH = "shared_branch"


class DirtyOp(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class DirtyPath:
    path: str
    op: DirtyOp


@dataclass(frozen=True)
class WorkspaceScopeResolution:
    """Resolved workspace scope.

    ``dirty_paths`` is the full dirty set. ``scoped_dirty_paths`` is the
    workspace-owned dirty subset, including deletions, for staging and index
    checks. ``scoped_existing_paths`` excludes deletions and missing paths for
    tools that require filesystem targets.
    """

    kind: WorkspaceScopeKind
    has_session_identity: bool
    dirty_paths: tuple[DirtyPath, ...]
    scoped_dirty_paths: tuple[str, ...]
    scoped_existing_paths: tuple[str, ...]


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


def resolve_workspace_scope_resolution(project_root: Path) -> WorkspaceScopeResolution:
    """Resolve dirty workspace metadata and action-ready scoped paths."""
    dirty_paths = _resolve_dirty_paths(project_root)
    session_id = get_session_id()
    has_session_identity = bool(session_id)

    if is_worktree(project_root):
        return WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=has_session_identity,
            dirty_paths=dirty_paths,
            scoped_dirty_paths=tuple(dirty.path for dirty in dirty_paths),
            scoped_existing_paths=_existing_dirty_paths(project_root, dirty_paths),
        )

    if not session_id:
        return WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=False,
            dirty_paths=dirty_paths,
            scoped_dirty_paths=(),
            scoped_existing_paths=(),
        )

    touched = _resolve_session_touched_paths(project_root)
    dirty_path_set = {dirty.path for dirty in dirty_paths}
    dirty_existing = set(_existing_dirty_paths(project_root, dirty_paths))
    scoped_dirty = tuple(sorted(path for path in touched if path in dirty_path_set))
    scoped = tuple(sorted(path for path in touched if path in dirty_existing))
    return WorkspaceScopeResolution(
        kind=WorkspaceScopeKind.SHARED_BRANCH,
        has_session_identity=True,
        dirty_paths=dirty_paths,
        scoped_dirty_paths=scoped_dirty,
        scoped_existing_paths=scoped,
    )


def _resolve_dirty_paths(project_root: Path) -> tuple[DirtyPath, ...]:
    repo = Repo(str(project_root))
    try:
        status = repo.git.status("--porcelain", "--untracked-files=all")
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to resolve dirty workspace paths: {exc}") from exc
    return tuple(_parse_dirty_status_line(line) for line in status.splitlines() if len(line) > 3)


def _parse_dirty_status_line(line: str) -> DirtyPath:
    status_code = line[:2]
    raw_path = line[3:].strip()
    path = raw_path.rsplit(" -> ", maxsplit=1)[-1]
    if "D" in status_code:
        op = DirtyOp.DELETED
    elif status_code == "??" or "A" in status_code:
        op = DirtyOp.ADDED
    else:
        op = DirtyOp.MODIFIED
    return DirtyPath(path=path, op=op)


def _existing_dirty_paths(project_root: Path, dirty_paths: tuple[DirtyPath, ...]) -> tuple[str, ...]:
    return tuple(
        dirty.path for dirty in dirty_paths if dirty.op is not DirtyOp.DELETED and (project_root / dirty.path).exists()
    )


def _resolve_session_touched_paths(project_root: Path) -> tuple[str, ...]:
    try:
        touched: set[str] = collect_session_touched_files(str(project_root))
    except Exception as exc:
        raise RuntimeError(f"Failed to collect session-touched files: {exc}") from exc
    return tuple(sorted(touched))


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
            logger.warning("Rejected traversal path from workspace scope: %s", p)
            continue
        if p.startswith("/") and not p.startswith(project_root_str):
            logger.warning("Rejected absolute path outside project root: %s", p)
            continue
        safe.append(p)
    return safe
