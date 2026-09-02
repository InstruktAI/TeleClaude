"""Shared types for session-scoping orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
    scope_mode: ScopeMode
    workspace_kind: WorkspaceKind
    strategy: str
    ledger_updated: bool


class AttributionSignal(StrEnum):
    """Whether foreign-session transcript attribution was resolved."""

    RESOLVED = "resolved"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class TouchEvidence:
    """One successful, timestamped mutation observed in a session transcript."""

    path: str
    touched_at: datetime


@dataclass(frozen=True)
class SessionAttributionResult:
    """Strict foreign-session attribution kept separate from workspace scope."""

    signal: AttributionSignal
    touches: tuple[TouchEvidence, ...]
    strategy: str
