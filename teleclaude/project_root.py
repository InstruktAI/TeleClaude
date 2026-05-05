"""Canonical TeleClaude path-root resolution."""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["resolve_invocation_cwd", "resolve_state_root", "resolve_workspace_root"]


def resolve_invocation_cwd() -> Path:
    """Return the user's actual invocation directory.

    The ``bin/telec`` wrapper uses ``uv run --directory "$INSTALL_DIR"`` so
    that uv can resolve the virtualenv from TeleClaude's installation root.
    That flag also sets the Python process's cwd to the installation root,
    which means ``Path.cwd()`` no longer reflects the directory the user was
    in when they ran ``telec``. Worktree detection and project-root resolution
    silently fail because the cwd now points at the main repo, not the actual
    invocation directory.

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


def resolve_workspace_root(start: str | Path) -> Path:
    """Return the checkout/worktree root where commands should execute.

    Walks up from ``start`` to find the nearest TeleClaude project checkout by
    locating ``teleclaude.yml``. In todo worktrees this returns the worktree
    root, not the main checkout.
    """
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    while True:
        if not current.name.startswith(".") and (current / "teleclaude.yml").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("No teleclaude.yml found in directory hierarchy")
        current = parent


def resolve_state_root(start: str | Path) -> Path:
    """Return the canonical main project root where shared state lives.

    Accepts a path at the repo root, inside the repo, or inside a git worktree.
    Falls back to the provided path when no git metadata can be found.
    """
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    original = current

    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir():
            return current
        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
            except OSError:
                return original
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (current / gitdir).resolve()
                for parent in gitdir.parents:
                    if parent.name == ".git":
                        return parent.parent
            return current
        current = current.parent

    return original
