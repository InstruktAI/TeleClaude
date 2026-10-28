"""Construct GitHub clients with the platform's shared transport posture."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from time import monotonic

import httpx
from githubkit.auth.base import BaseAuthStrategy
from githubkit.cache.base import BaseCacheStrategy
from githubkit.github import GitHub
from instrukt_ai_logging import get_logger

_AUTO_RETRY = False
_HTTP_CACHE = False
_FOLLOW_REDIRECTS = False
_TRUST_ENV = False
_TIMEOUT_SECONDS = 10.0
_MS_PER_SECOND = 1000
_REQUEST_TIMED = "github_request_timed"
# How long an idle pooled connection stays open for the next gated request.
_KEEPALIVE_EXPIRY_SECONDS = 60.0

logger = get_logger(__name__)

RequestGate = Callable[[], AbstractAsyncContextManager[object]]


def create_connection_pool() -> httpx.AsyncHTTPTransport:
    """Create a connection pool with the platform's transport posture, for an owner to share and close.

    The pool belongs to the event loop it is first used on; its owner keeps it on that loop.
    """
    return httpx.AsyncHTTPTransport(
        trust_env=_TRUST_ENV, limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY_SECONDS)
    )


class _GatedTransport(httpx.AsyncBaseTransport):
    """Send each wire request inside the caller's gate, leaving it once the response is read.

    The transport keeps the posture the client would have built for itself (environment trust disabled).
    With a caller's shared pool, consecutive clients reuse its open connections instead of each paying a new
    TCP and TLS handshake, and closing the client leaves the pool to its owner; without one, the transport
    owns a pool of its own and closes it with the client. Each request logs how long it waited for the gate
    and how long it spent on the wire.
    """

    def __init__(self, gate: RequestGate, pool: httpx.AsyncHTTPTransport | None) -> None:
        self._gate = gate
        self._shared = pool is not None
        self._wire = pool if pool is not None else create_connection_pool()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        queued = monotonic()
        async with self._gate():
            sent = monotonic()
            response = await self._wire.handle_async_request(request)
            await response.aread()
        done = monotonic()
        logger.debug(
            _REQUEST_TIMED,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            gate_wait_ms=round((sent - queued) * _MS_PER_SECOND),
            wire_ms=round((done - sent) * _MS_PER_SECOND),
        )
        return response

    async def aclose(self) -> None:
        if not self._shared:
            await self._wire.aclose()


def create_github_client[AuthStrategyT: BaseAuthStrategy](
    auth: AuthStrategyT,
    cache: BaseCacheStrategy,
    *,
    request_gate: RequestGate | None = None,
    connection_pool: httpx.AsyncHTTPTransport | None = None,
) -> GitHub[AuthStrategyT]:
    """Create one client with retries, caching, redirects, and env trust disabled.

    A caller that must schedule every wire request passes the gate each request runs inside, and may pass
    the connection pool it owns so its clients share connections.
    """
    return GitHub(
        auth,
        cache_strategy=cache,
        auto_retry=_AUTO_RETRY,
        http_cache=_HTTP_CACHE,
        follow_redirects=_FOLLOW_REDIRECTS,
        trust_env=_TRUST_ENV,
        timeout=_TIMEOUT_SECONDS,
        async_transport=None if request_gate is None else _GatedTransport(request_gate, connection_pool),
    )
