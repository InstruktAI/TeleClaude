"""Shared repository-root resolution for worktree-safe bootstrap paths."""

from __future__ import annotations

from pathlib import Path


def resolve_main_repo_root(start: Path) -> Path:
    """Resolve the main git repository root, even when invoked from a worktree."""
    current = start
    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir():
            return current
        if git_path.is_file():
            try:
                content = git_path.read_text().strip()
            except OSError:
                return current
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
                if not gitdir.is_absolute():
                    gitdir = (current / gitdir).resolve()
                for parent in gitdir.parents:
                    if parent.name == ".git":
                        return parent.parent
            return current
        current = current.parent
    return start
