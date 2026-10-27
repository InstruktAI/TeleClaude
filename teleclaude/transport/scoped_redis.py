"""Clients for the two Redis instances, built from ``config.redis``: this computer's local Redis and the cluster's."""

from __future__ import annotations

from redis.asyncio import Redis

from teleclaude.config.machine import config
from teleclaude.events.scope import ScopedClients
from teleclaude.transport.redis_client import create_redis_client


def local_redis_client() -> Redis:
    """A client of this computer's own Redis, which carries its local events."""
    local = config.redis.local
    return create_redis_client(
        local.url,
        username=local.username,
        password=local.password,
        max_connections=local.max_connections,
        socket_timeout=local.socket_timeout,
    )


def cluster_redis_client() -> Redis:
    """A client of the shared cluster Redis, which carries cluster events and the cross-computer transport."""
    cluster = config.redis.cluster
    return create_redis_client(
        cluster.url,
        password=cluster.password,
        max_connections=cluster.max_connections,
        socket_timeout=cluster.socket_timeout,
    )


def scoped_redis_clients() -> ScopedClients[Redis]:
    """A client of each scope's Redis."""
    return ScopedClients(local=local_redis_client(), cluster=cluster_redis_client())
