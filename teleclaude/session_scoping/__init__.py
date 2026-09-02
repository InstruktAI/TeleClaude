"""Shared public session-scoping API."""

from ._api import resolve_scoped_paths
from ._attribution import resolve_session_attribution
from ._types import (
    AttributionSignal,
    ScopedPathsResult,
    ScopeMode,
    SessionAttributionResult,
    TouchEvidence,
    WorkspaceKind,
)

__all__ = [
    "AttributionSignal",
    "ScopeMode",
    "ScopedPathsResult",
    "SessionAttributionResult",
    "TouchEvidence",
    "WorkspaceKind",
    "resolve_scoped_paths",
    "resolve_session_attribution",
]
