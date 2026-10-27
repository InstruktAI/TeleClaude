"""Construct GitHub clients with the platform's shared transport posture."""

from __future__ import annotations

import httpx
from githubkit.auth.base import BaseAuthStrategy
from githubkit.cache.base import BaseCacheStrategy
from githubkit.github import GitHub

_AUTO_RETRY = False
_HTTP_CACHE = False
_FOLLOW_REDIRECTS = False
_TRUST_ENV = False
_TIMEOUT_SECONDS = 10.0


def create_github_client[AuthStrategyT: BaseAuthStrategy](
    auth: AuthStrategyT, cache: BaseCacheStrategy, *, async_transport: httpx.AsyncBaseTransport | None = None
) -> GitHub[AuthStrategyT]:
    """Create one client with retries, caching, redirects, and env trust disabled.

    A caller that must schedule every wire request passes the transport that does it.
    """
    return GitHub(
        auth,
        cache_strategy=cache,
        auto_retry=_AUTO_RETRY,
        http_cache=_HTTP_CACHE,
        follow_redirects=_FOLLOW_REDIRECTS,
        trust_env=_TRUST_ENV,
        timeout=_TIMEOUT_SECONDS,
        async_transport=async_transport,
    )
