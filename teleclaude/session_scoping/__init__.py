"""Shared public session-scoping API."""

from ._api import resolve_scoped_paths
from ._types import ScopedPathsResult, ScopeMode, WorkspaceKind

__all__ = [
    "ScopeMode",
    "ScopedPathsResult",
    "WorkspaceKind",
    "resolve_scoped_paths",
]
