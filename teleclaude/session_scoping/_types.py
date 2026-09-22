"""Shared types for session-scoping orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ScopeMode = Literal["turn_delta", "session_dirty"]
WorkspaceKind = Literal["git_worktree", "git_shared", "non_git", "none"]


@dataclass(frozen=True)
class ResolvedWorkspace:
    """Canonical workspace root and workspace kind."""

    root: str | None
    kind: WorkspaceKind


@dataclass(frozen=True)
class ScopedPathsResult:
    """Result returned by the shared session-scoping API."""

    paths: tuple[str, ...]
    declared_paths: tuple[str, ...]
    scope_mode: ScopeMode
    workspace_kind: WorkspaceKind
    strategy: str
    ledger_updated: bool


@dataclass(frozen=True)
class DeclarationEvidence:
    """One successful sealed-add declaration that remains live."""

    path: str
    declared_at: datetime
