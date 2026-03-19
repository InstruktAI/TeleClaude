"""Leaf operation-progress bridge used by operations and next-machine."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

_progress_callback: ContextVar[Callable[[str, str, str], None] | None] = ContextVar(
    "operations_progress_callback",
    default=None,
)


def set_progress_callback(
    callback: Callable[[str, str, str], None] | None,
) -> Token[Callable[[str, str, str], None] | None]:
    """Install a progress callback for the current context."""
    return _progress_callback.set(callback)


def reset_progress_callback(token: Token[Callable[[str, str, str], None] | None]) -> None:
    """Restore the previous progress callback."""
    _progress_callback.reset(token)


def emit_operation_progress(phase: str, decision: str, reason: str) -> None:
    """Forward next-machine phase updates to the active operation, if any."""
    callback = _progress_callback.get()
    if callback is not None:
        callback(phase, decision, reason)
