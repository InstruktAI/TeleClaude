"""Leaf caller-identity bridge used by operations and session_identity."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

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


@dataclass(frozen=True)
class RelayedCaller:
    """The address of a caller session whose request another computer carried here."""

    computer: str
    session_id: str | None


_relayed_caller: ContextVar[RelayedCaller | None] = ContextVar(
    "relayed_caller",
    default=None,
)


def set_relayed_caller(value: RelayedCaller | None) -> Token[RelayedCaller | None]:
    """Install the address of the relayed caller for the current context."""
    return _relayed_caller.set(value)


def reset_relayed_caller(token: Token[RelayedCaller | None]) -> None:
    """Restore the previous relayed caller."""
    _relayed_caller.reset(token)


def get_relayed_caller() -> RelayedCaller | None:
    """Return the relayed caller of the request being run, or None for a request made on this computer."""
    return _relayed_caller.get()


def relayed_caller_computer(caller_session_id: str | None) -> str | None:
    """The computer holding ``caller_session_id`` when the request being run was carried here from it."""
    relayed = _relayed_caller.get()
    return relayed.computer if relayed is not None and relayed.session_id == caller_session_id else None
