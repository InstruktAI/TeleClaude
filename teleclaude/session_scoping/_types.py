"""Shared types for session-scoping orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class WorkspaceKind(StrEnum):
    """How the resolved workspace root relates to its git repository."""

    GIT_WORKTREE = "git_worktree"
    GIT_SHARED = "git_shared"
    NON_GIT = "non_git"
    NONE = "none"


@dataclass(frozen=True)
class ResolvedWorkspace:
    """Canonical workspace root and workspace kind."""

    root: str | None
    kind: WorkspaceKind


@dataclass(frozen=True)
class DeclarationEvidence:
    """One successful sealed-add declaration that remains live."""

    path: str
    declared_at: datetime
