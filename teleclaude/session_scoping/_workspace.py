"""Workspace-root resolution for session scoping."""

from __future__ import annotations

from pathlib import Path

from ._types import ResolvedWorkspace, WorkspaceKind

__all__ = ["resolve_workspace"]


def resolve_workspace(workspace_root: str | None) -> ResolvedWorkspace:
    """Resolve workspace root and workspace kind from an arbitrary path."""
    if not workspace_root:
        return ResolvedWorkspace(root=None, kind=WorkspaceKind.NONE)

    current = Path(workspace_root).expanduser().resolve()
    if current.is_file():
        current = current.parent
    original = current

    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir():
            return ResolvedWorkspace(root=str(current), kind=WorkspaceKind.GIT_SHARED)
        if git_path.is_file():
            return ResolvedWorkspace(root=str(current), kind=WorkspaceKind.GIT_WORKTREE)
        current = current.parent

    return ResolvedWorkspace(root=str(original), kind=WorkspaceKind.NON_GIT)
