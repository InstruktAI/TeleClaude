"""Shared public session-scoping API."""

from ._api import resolve_scoped_paths
from ._candidates import undeclared_shell_write_candidates
from ._edit_declarations import certain_edit_paths
from ._record import clear, declare, live_declarations
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
    "certain_edit_paths",
    "clear",
    "declare",
    "live_declarations",
    "resolve_scoped_paths",
    "resolve_workspace",
    "undeclared_shell_write_candidates",
]
