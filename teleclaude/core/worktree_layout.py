"""Dependency-free paths and predicates for workflow worktrees."""

from __future__ import annotations

from pathlib import Path

WORKTREE_DIR = "trees"
INTEGRATION_WORKTREE_NAME = "_integration"
WORKTREE_HOMES_DIR = ".homes"


def is_integration_worktree(root: Path) -> bool:
    """Return whether root is the integration checkout."""
    return root.parent.name == WORKTREE_DIR and root.name == INTEGRATION_WORKTREE_NAME


def is_slug_worktree(root: Path) -> bool:
    """Return whether root is a todo slug checkout."""
    return root.parent.name == WORKTREE_DIR and not is_integration_worktree(root)


def worktree_home_for_checkout(root: Path) -> Path | None:
    """Return the home clone path for a slug worktree checkout."""
    if not is_slug_worktree(root):
        return None
    return root.parent / WORKTREE_HOMES_DIR / root.name
