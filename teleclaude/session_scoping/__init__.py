"""Shared public session-scoping API."""

from ._api import resolve_scoped_paths
from ._record import clear, declare, discard, live_declarations
from ._types import (
    DeclarationEvidence,
    ScopedPathsResult,
    ScopeMode,
    WorkspaceKind,
)
from ._workspace import resolve_workspace

__all__ = [
    "DeclarationEvidence",
    "ScopeMode",
    "ScopedPathsResult",
    "WorkspaceKind",
    "clear",
    "declare",
    "discard",
    "live_declarations",
    "resolve_scoped_paths",
    "resolve_workspace",
]
