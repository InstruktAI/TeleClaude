"""Workspace-root resolution for session scoping."""

from __future__ import annotations

from teleclaude.git import is_linked_worktree
from teleclaude.project_root import resolve_git_root

from ._types import ResolvedWorkspace, WorkspaceKind

__all__ = ["resolve_workspace"]


def resolve_workspace(workspace_root: str | None) -> ResolvedWorkspace:
    """Resolve workspace root and workspace kind from an arbitrary path."""
    if not workspace_root:
        return ResolvedWorkspace(root=None, kind=WorkspaceKind.NONE)

    root = resolve_git_root(workspace_root)
    git_path = root / ".git"
    if git_path.is_dir() or git_path.is_file():
        kind = WorkspaceKind.GIT_WORKTREE if is_linked_worktree(root) else WorkspaceKind.GIT_SHARED
        return ResolvedWorkspace(root=str(root), kind=kind)

    return ResolvedWorkspace(root=str(root), kind=WorkspaceKind.NON_GIT)
