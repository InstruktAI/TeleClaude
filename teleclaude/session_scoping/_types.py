"""Shared types for session-scoping orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ScopeMode = Literal["turn_delta", "session_dirty", "workspace_dirty"]
WorkspaceKind = Literal["git_worktree", "git_shared", "non_git", "none"]


@dataclass(frozen=True)
class ResolvedWorkspace:
    """Canonical workspace root and workspace kind."""

    root: str | None
    kind: WorkspaceKind


@dataclass(frozen=True)
class WorkspaceScopeLedger:
    """Durable ledger entry for one session/workspace pair."""

    workspace_root: str
    workspace_kind: WorkspaceKind
    strategy: str
    agent: str
    seen_paths: tuple[str, ...]
    last_updated: str


@dataclass(frozen=True)
class ScopedPathsResult:
    """Result returned by the shared session-scoping API."""

    paths: tuple[str, ...]
    scope_mode: ScopeMode
    workspace_kind: WorkspaceKind
    strategy: str
    ledger_updated: bool
