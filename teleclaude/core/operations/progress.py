"""Shared operation-progress callback helpers."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

ProgressCallback = Callable[[str, str, str], None]

_progress_callback: ContextVar[ProgressCallback | None] = ContextVar(
    "operations_progress_callback",
    default=None,
)


def emit_operation_progress(phase: str, decision: str, reason: str) -> None:
    """Forward next-machine progress to the active operation callback, if any."""
    callback = _progress_callback.get()
    if callback is not None:
        try:
            callback(phase, decision, reason)
        except Exception:
            return


def set_operation_progress_callback(callback: ProgressCallback | None) -> Token[ProgressCallback | None]:
    """Install the current operation progress callback."""
    return _progress_callback.set(callback)


def reset_operation_progress_callback(token: Token[ProgressCallback | None]) -> None:
    """Restore the previous operation progress callback."""
    _progress_callback.reset(token)
