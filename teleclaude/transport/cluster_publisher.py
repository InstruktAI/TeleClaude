"""Helper for publishing ``cluster.*`` events from the local daemon.

Every cross-computer state mutation goes through this single emit point so the
``ClusterBridge`` on every peer (including the publisher itself) observes it.
Publishing is fire-and-forget; failures are logged but do not propagate, since
the local mutation has already committed by the time we publish.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.transport.cluster_bridge import CLUSTER_ENVELOPE_SCHEMA_VERSION

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


_PUBLISH_EXCEPTIONS = (RedisError, OSError, TimeoutError, RuntimeError, TypeError, ValueError)


class ClusterPublisher:
    """Publish ``cluster.*`` envelopes onto Redis pub/sub.

    The publisher holds a reference to a redis-client provider rather than a
    bound client, so it survives daemon reconnects without holding stale
    handles. ``origin`` is fixed to the local computer name at construction.
    """

    def __init__(
        self,
        *,
        origin: str,
        redis_provider: Callable[[], Awaitable[Redis]],
    ) -> None:
        self._origin = origin
        self._redis_provider = redis_provider

    @property
    def origin(self) -> str:
        return self._origin

    async def publish(
        self,
        channel: str,
        payload: dict[str, object],  # guard: loose-dict - event-specific payload, owned by call site
    ) -> bool:
        """Publish a single envelope. Returns True if Redis accepted the publish."""
        envelope = {
            "schema_version": CLUSTER_ENVELOPE_SCHEMA_VERSION,
            "channel": channel,
            "idempotency_key": uuid.uuid4().hex,
            "emitted_at": datetime.now(UTC).isoformat(),
            "origin": self._origin,
            "payload": payload,
        }
        try:
            redis = await self._redis_provider()
            await redis.publish(channel, json.dumps(envelope))
            return True
        except _PUBLISH_EXCEPTIONS as exc:
            logger.warning(
                "Cluster publish failed; cache already mutated locally",
                channel=channel,
                error=str(exc),
            )
            return False
