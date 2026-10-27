"""Clients for each event scope's Redis, built from ``config.redis``.

A computer whose local Redis is not configured carries its local events on the cluster Redis, as it did before
each scope had its own Redis; its local scope then shares the cluster client.
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from teleclaude.config.machine import config
from teleclaude.events.scope import ScopedClients
from teleclaude.transport.redis_client import create_redis_client


def local_redis_configured() -> bool:
    """Whether this computer has its own local Redis for local events."""
    return bool(config.redis.local.url)


def cluster_redis_client() -> Redis:
    """A client of the cluster Redis; a lone computer's cluster settings name its own local Redis (ADR-0144)."""
    cluster = config.redis.cluster
    return create_redis_client(
        cluster.required_url(),
        username=cluster.username,
        password=cluster.password,
        max_connections=cluster.max_connections,
        socket_timeout=cluster.socket_timeout,
    )


def scoped_redis_clients() -> ScopedClients[Redis]:
    """A client of each scope's Redis, shared when both scopes name the same Redis or no local Redis is configured."""
    cluster = cluster_redis_client()
    local = config.redis.local
    same_redis = (local.url, local.username) == (config.redis.cluster.url, config.redis.cluster.username)
    if not local.url or same_redis:
        return ScopedClients(local=cluster, cluster=cluster)
    return ScopedClients(
        local=create_redis_client(
            local.url,
            username=local.username,
            password=local.password,
            max_connections=local.max_connections,
            socket_timeout=local.socket_timeout,
        ),
        cluster=cluster,
    )


async def close_scoped_clients(clients: ScopedClients[Any]) -> None:
    """Close each distinct client, the later ones even when an earlier close raised."""
    first, *rest = clients.distinct()
    try:
        await first.aclose()
    finally:
        for client in rest:
            await client.aclose()
