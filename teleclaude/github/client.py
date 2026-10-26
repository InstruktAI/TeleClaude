"""Construct GitHub clients with the platform's shared transport posture."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
from githubkit.auth.base import BaseAuthStrategy
from githubkit.cache.base import BaseCacheStrategy
from githubkit.github import GitHub

_AUTO_RETRY = False
_HTTP_CACHE = False
_FOLLOW_REDIRECTS = False
_TRUST_ENV = False
_TIMEOUT_SECONDS = 10.0
_RESPONSE_EVENT = "response"

type ResponseObserver = Callable[[httpx.Response], Awaitable[None]]


def create_github_client[AuthStrategyT: BaseAuthStrategy](
    auth: AuthStrategyT, cache: BaseCacheStrategy, *, response_observer: ResponseObserver | None = None
) -> GitHub[AuthStrategyT]:
    """Create one client with retries, caching, redirects, and env trust disabled.

    ``response_observer`` sees every response, including a refused one, before the SDK interprets it.
    """
    return GitHub(
        auth,
        cache_strategy=cache,
        auto_retry=_AUTO_RETRY,
        http_cache=_HTTP_CACHE,
        follow_redirects=_FOLLOW_REDIRECTS,
        trust_env=_TRUST_ENV,
        timeout=_TIMEOUT_SECONDS,
        async_event_hooks={_RESPONSE_EVENT: [response_observer]} if response_observer is not None else None,
    )
