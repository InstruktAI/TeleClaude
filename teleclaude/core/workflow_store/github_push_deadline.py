"""The push deadline: the monotonic bound on one push's GitHub I/O while it owns the working copy's writer."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from teleclaude.core.todos_db._write_admission import PUSH_DEADLINE_S, owned_request_scope, refuse_write
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused

PUSH_DEADLINE_KEY = "github_store_push_deadline"
COMMIT_POINT_SENT_KEY = "github_store_commit_point_sent"
_PUSH_DEADLINE_DETAIL = "push deadline exceeded"


@dataclass(frozen=True)
class PushDeadline:
    """The monotonic end of one push's GitHub I/O, and whether the API request's deadline set it."""

    at: float
    from_request: bool

    @property
    def remaining(self) -> float:
        return self.at - time.monotonic()


def begin_push_deadline() -> PushDeadline:
    """Bound a push by the push deadline, or by the end of the owning API request when that comes first."""
    at = time.monotonic() + PUSH_DEADLINE_S
    scope = owned_request_scope()
    if scope is not None and scope.deadline <= at:
        return PushDeadline(scope.deadline, from_request=True)
    return PushDeadline(at, from_request=False)


def push_deadline_expired(deadline: PushDeadline, *, commit_point_sent: bool) -> Exception:
    """The refusal for a push whose GitHub I/O outlasted its deadline.

    The request's own deadline reaches the API as the store's published refusal; the push deadline alone is a
    provider failure, which aborts the local commit through the existing route.
    """
    if deadline.from_request:
        return refuse_write(commit_point_sent=commit_point_sent)
    return GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_PUSH_DEADLINE_DETAIL)


async def await_within_push_deadline(
    deadline: PushDeadline, awaitable: Awaitable[Any], *, commit_point_sent: bool
) -> Any:
    """Await a GitHub request under a push deadline, cancelling it when the deadline passes."""
    try:
        return await asyncio.wait_for(awaitable, max(deadline.remaining, 0.0))
    except TimeoutError:
        raise push_deadline_expired(deadline, commit_point_sent=commit_point_sent) from None
