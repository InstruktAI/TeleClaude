"""Shared public session-scoping API."""

from ._candidates import undeclared_shell_write_candidates
from ._edit_declarations import certain_edit_paths
from ._record import clear, declare, live_declarations
from ._types import (
    DeclarationEvidence,
    WorkspaceKind,
)
from ._workspace import resolve_workspace

__all__ = [
    "DeclarationEvidence",
    "WorkspaceKind",
    "certain_edit_paths",
    "clear",
    "declare",
    "live_declarations",
    "resolve_workspace",
    "undeclared_shell_write_candidates",
]
