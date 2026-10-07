"""Leaf follow-through bridge used by operations and next-machine.

A state machine running inside an operation can owe an action that must happen only
after the operation's own result has been recorded and delivered to its caller. It
defers that action here; the operation runner starts the deferred actions once the
outcome has been delivered. An operation that fails starts none.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar

FollowThrough = Callable[[], Coroutine[object, object, object]]

_NO_OPERATION_SCOPE_MESSAGE = "a follow-through can only be deferred from inside a running operation"

_follow_throughs: ContextVar[list[FollowThrough] | None] = ContextVar(
    "operations_follow_throughs",
    default=None,
)


@asynccontextmanager
async def follow_through_scope() -> AsyncIterator[list[FollowThrough]]:
    """Collect the follow-throughs deferred while the current operation runs."""
    scope: list[FollowThrough] = []
    token = _follow_throughs.set(scope)
    try:
        yield scope
    finally:
        _follow_throughs.reset(token)


def defer_follow_through(follow_through: FollowThrough) -> None:
    """Defer ``follow_through`` until the running operation's outcome has been delivered."""
    scope = _follow_throughs.get()
    if scope is None:
        raise RuntimeError(_NO_OPERATION_SCOPE_MESSAGE)
    scope.append(follow_through)
