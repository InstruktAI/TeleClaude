"""Shared scope utilities for quality tooling.

Worktree detection, session scope resolution, project root resolution,
language detection, and path validation used by both lint and test runners.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def resolve_invocation_cwd() -> Path:
    """Return the user's actual invocation directory.

    The ``bin/telec`` wrapper uses ``uv run --directory "$INSTALL_DIR"`` so
    that uv can resolve the virtualenv from TeleClaude's installation root.
    That flag also sets the Python process's cwd to the installation root,
    which means ``Path.cwd()`` no longer reflects the directory the user was
    in when they ran ``telec``. Worktree detection silently fails because
    the cwd now points at the main repo, not the worktree.

    The wrapper mitigates by exporting ``TELEC_INVOCATION_CWD=$PWD`` before
    exec'ing uv. Handlers read that first. ``$PWD`` is the secondary
    fallback — shell-exported PWD survives across ``uv run`` because uv
    inherits the environment. ``Path.cwd()`` is the last resort for direct
    module invocations that never went through the wrapper.

    Resolution order:
    1. ``TELEC_INVOCATION_CWD`` (wrapper-exported, authoritative).
    2. ``PWD`` (shell environment, survives ``uv run --directory``).
    3. ``Path.cwd()`` (process cwd; potentially hijacked by uv).
    """
    explicit = os.environ.get("TELEC_INVOCATION_CWD")
    if explicit:
        return Path(explicit)
    pwd = os.environ.get("PWD")
    if pwd:
        return Path(pwd)
    return Path.cwd()


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
    from teleclaude.session_identity import (  # pylint: disable=import-outside-toplevel  # deferred: heavy transitive imports
        get_session_id,
    )

    session_id = get_session_id()
    if not session_id:
        raise RuntimeError("No active session identity")

    try:
        from teleclaude.todo_scaffold import (  # pylint: disable=import-outside-toplevel  # deferred: heavy transitive imports
            _collect_session_touched_files,
        )

        touched: set[str] = _collect_session_touched_files(str(project_root))
    except Exception as exc:
        raise RuntimeError(f"Failed to collect session-touched files: {exc}") from exc

    # Filter to files that exist on disk — session transcripts may reference
    # example paths from docstrings that aren't real files.
    existing = [f for f in sorted(touched) if (project_root / f).exists()]
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
