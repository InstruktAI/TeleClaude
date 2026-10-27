"""Run one unit of GitHub work serialized behind the process-wide unit lock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future

from teleclaude.core.workflow_store.github_io_runtime import shared_github_io_loop
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused

_LOCK_WAIT_SECONDS = 30.0
_UNIT_SECONDS = 180.0
_LOCK_WAIT_DETAIL = "unit lock wait exceeded"
_UNIT_DETAIL = "unit of work exceeded its time bound"


def submit_serialized_unit[Result](work: Callable[[], Awaitable[Result]]) -> Future[Result]:
    """Queue one unit of GitHub work on the shared I/O loop behind the process-wide unit lock.

    The wait for the lock and the unit itself are bounded, so a caller with a deadline is answered
    with a refusal instead of an unbounded wait.
    """
    return shared_github_io_loop().submit(_run_serialized_unit(work))


async def _run_serialized_unit[Result](work: Callable[[], Awaitable[Result]]) -> Result:
    io_loop = shared_github_io_loop()
    if io_loop.unit_lock is None:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE)
    try:
        await asyncio.wait_for(io_loop.unit_lock.acquire(), _LOCK_WAIT_SECONDS)
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_LOCK_WAIT_DETAIL) from None
    try:
        async with asyncio.timeout(_UNIT_SECONDS):
            return await work()
    except TimeoutError:
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_UNIT_DETAIL) from None
    finally:
        io_loop.unit_lock.release()
