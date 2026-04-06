"""Canonical project-root resolution for repo-root and worktree paths."""

from __future__ import annotations

from pathlib import Path

__all__ = ["resolve_main_repo_root"]


def resolve_main_repo_root(start: str | Path) -> Path:
    """Resolve the main git repository root for *start*.

    Accepts a path at the repo root, inside the repo, or inside a git worktree.
    Falls back to the provided path when no git metadata can be found.
    """
    current = Path(start).expanduser()
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
