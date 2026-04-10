"""Leaf caller-identity bridge used by operations and session_identity."""

from __future__ import annotations

from contextvars import ContextVar, Token

_caller_session_id: ContextVar[str | None] = ContextVar(
    "operations_caller_session_id",
    default=None,
)


def set_caller_session_id(value: str | None) -> Token[str | None]:
    """Install a caller session id for the current context."""
    return _caller_session_id.set(value)


def reset_caller_session_id(token: Token[str | None]) -> None:
    """Restore the previous caller session id."""
    _caller_session_id.reset(token)


def get_caller_session_id() -> str | None:
    """Return the caller session id for the current context, or None."""
    return _caller_session_id.get()
