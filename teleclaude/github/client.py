"""Construct GitHub clients with the platform's shared transport posture."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from time import monotonic
from weakref import WeakKeyDictionary

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

# One connection pool per event loop, shared by every gated client on it; dropped with its loop.
_loop_wires: WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncHTTPTransport] = WeakKeyDictionary()


def _loop_wire() -> httpx.AsyncHTTPTransport:
    """Return the running loop's pooled transport, creating it on first use."""
    loop = asyncio.get_running_loop()
    wire = _loop_wires.get(loop)
    if wire is None:
        wire = httpx.AsyncHTTPTransport(
            trust_env=_TRUST_ENV, limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY_SECONDS)
        )
        _loop_wires[loop] = wire
    return wire


class _GatedTransport(httpx.AsyncBaseTransport):
    """Send each wire request inside the caller's gate, leaving it once the response is read.

    The transport keeps the posture the client would have built for itself (environment trust disabled).
    Requests share the running loop's connection pool, so consecutive clients reuse open connections
    instead of each paying a new TCP and TLS handshake. Each request logs how long it waited for the gate
    and how long it spent on the wire.
    """

    def __init__(self, gate: RequestGate) -> None:
        self._gate = gate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        queued = monotonic()
        async with self._gate():
            sent = monotonic()
            response = await _loop_wire().handle_async_request(request)
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
        """Leave the loop's shared pool open for the next client."""


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
