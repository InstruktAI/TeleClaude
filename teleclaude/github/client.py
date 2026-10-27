"""Construct GitHub clients with the platform's shared transport posture."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
from githubkit.auth.base import BaseAuthStrategy
from githubkit.cache.base import BaseCacheStrategy
from githubkit.github import GitHub

_AUTO_RETRY = False
_HTTP_CACHE = False
_FOLLOW_REDIRECTS = False
_TRUST_ENV = False
_TIMEOUT_SECONDS = 10.0


RequestGate = Callable[[], AbstractAsyncContextManager[object]]


class _GatedTransport(httpx.AsyncBaseTransport):
    """Send each wire request inside the caller's gate, leaving it once the response is read.

    The transport keeps the posture the client would have built for itself (environment trust disabled).
    """

    def __init__(self, gate: RequestGate) -> None:
        self._gate = gate
        self._wire = httpx.AsyncHTTPTransport(trust_env=_TRUST_ENV)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with self._gate():
            response = await self._wire.handle_async_request(request)
            await response.aread()
        return response

    async def aclose(self) -> None:
        await self._wire.aclose()


def create_github_client[AuthStrategyT: BaseAuthStrategy](
    auth: AuthStrategyT, cache: BaseCacheStrategy, *, request_gate: RequestGate | None = None
) -> GitHub[AuthStrategyT]:
    """Create one client with retries, caching, redirects, and env trust disabled.

    A caller that must schedule every wire request passes the gate each request runs inside.
    """
    return GitHub(
        auth,
        cache_strategy=cache,
        auto_retry=_AUTO_RETRY,
        http_cache=_HTTP_CACHE,
        follow_redirects=_FOLLOW_REDIRECTS,
        trust_env=_TRUST_ENV,
        timeout=_TIMEOUT_SECONDS,
        async_transport=None if request_gate is None else _GatedTransport(request_gate),
    )
