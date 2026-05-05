"""Shared Redis client factory used by the daemon transport and CLI publishers.

This module is intentionally a leaf — it imports only `redis.asyncio` and `ssl`
so it can be pulled in from anywhere without dragging the full Redis transport
package (and its command-handler dependencies) into the import graph.
"""

from __future__ import annotations

import ssl

from redis.asyncio import Redis


def create_redis_client(
    redis_url: str,
    *,
    password: str | None,
    max_connections: int,
    socket_timeout: float | None,
    health_check_interval: int = 10,
) -> Redis:
    """Construct a Redis client honoring URL scheme, auth, and connection limits.

    Single source of truth for Redis client construction across the daemon
    transport and short-lived CLI publishers. ``rediss://`` URLs disable SSL
    cert verification to match the daemon's existing behavior.
    """
    if redis_url.startswith("rediss://"):
        return Redis.from_url(
            redis_url,
            password=password,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            health_check_interval=health_check_interval,
            decode_responses=False,
            ssl_cert_reqs=ssl.CERT_NONE,
        )
    return Redis.from_url(
        redis_url,
        password=password,
        max_connections=max_connections,
        socket_timeout=socket_timeout,
        health_check_interval=health_check_interval,
        decode_responses=False,
    )
