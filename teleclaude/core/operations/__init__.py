"""Receipt-backed durable operation helpers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.core.operations.progress import emit_operation_progress
    from teleclaude.core.operations.service import (
        OPERATION_KIND_TODO_WORK,
        OperationsService,
        get_operations_service,
        set_operations_service,
    )

__all__ = [
    "OPERATION_KIND_TODO_WORK",
    "OperationsService",
    "emit_operation_progress",
    "get_operations_service",
    "set_operations_service",
]

_SERVICE_EXPORTS = {
    "OPERATION_KIND_TODO_WORK",
    "OperationsService",
    "get_operations_service",
    "set_operations_service",
}


def __getattr__(name: str) -> object:
    """Lazily resolve service exports to avoid package-import cycles."""
    if name == "emit_operation_progress":
        return getattr(import_module("teleclaude.core.operations.progress"), name)
    if name in _SERVICE_EXPORTS:
        return getattr(import_module("teleclaude.core.operations.service"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
