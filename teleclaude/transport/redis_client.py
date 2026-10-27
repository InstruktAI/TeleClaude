"""Shared Redis client factory used by the daemon transport and CLI publishers.

This module is intentionally a leaf — it imports only `redis.asyncio`, `ssl`,
and leaf constants from `teleclaude.constants`, so it can be pulled in from
anywhere without dragging the full Redis transport package (and its
command-handler dependencies) into the import graph.
"""

from __future__ import annotations

import ssl

from redis.asyncio import BlockingConnectionPool, Redis

from teleclaude.constants import REDIS_POOL_TIMEOUT


def create_redis_client(
    redis_url: str,
    *,
    password: str | None,
    username: str | None = None,
    max_connections: int,
    socket_timeout: float | None,
    health_check_interval: int = 10,
) -> Redis:
    """Construct a Redis client honoring URL scheme, auth, and connection limits.

    Single source of truth for Redis client construction across the daemon
    transport and short-lived CLI publishers. ``rediss://`` URLs disable SSL
    cert verification to match the daemon's existing behavior.

    Connections are drawn from a bounded-backpressure
    :class:`~redis.asyncio.BlockingConnectionPool`: when all ``max_connections``
    are in use, acquisition blocks up to ``REDIS_POOL_TIMEOUT`` seconds for a
    release instead of failing fast, so a transient saturation waits rather than
    raising ``MaxConnectionsError`` across every subsystem at once. The client
    owns the pool (via :meth:`Redis.from_pool`), so ``aclose()`` disconnects it.
    """
    if redis_url.startswith("rediss://"):
        pool = BlockingConnectionPool.from_url(
            redis_url,
            username=username,
            password=password,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            health_check_interval=health_check_interval,
            decode_responses=False,
            timeout=REDIS_POOL_TIMEOUT,
            ssl_cert_reqs=ssl.CERT_NONE,
        )
    else:
        pool = BlockingConnectionPool.from_url(
            redis_url,
            username=username,
            password=password,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            health_check_interval=health_check_interval,
            decode_responses=False,
            timeout=REDIS_POOL_TIMEOUT,
        )
    return Redis.from_pool(pool)
