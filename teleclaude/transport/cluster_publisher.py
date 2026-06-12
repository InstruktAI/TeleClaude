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

from teleclaude.core.reconciliation import (
    DEFAULT_FEATURE_ID_REGISTRY,
    FeatureIDRegistry,
    FeatureMark,
    FleetCapabilityMap,
)
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
        registry: FeatureIDRegistry = DEFAULT_FEATURE_ID_REGISTRY,
        capability_map_provider: Callable[[], FleetCapabilityMap | None] | None = None,
    ) -> None:
        self._origin = origin
        self._redis_provider = redis_provider
        self._registry = registry
        self._capability_map_provider = capability_map_provider

    @property
    def origin(self) -> str:
        return self._origin

    async def publish(
        self,
        channel: str,
        payload: dict[str, object],  # guard: loose-dict - event-specific payload, owned by call site
        *,
        feature_id: str | None = None,
    ) -> bool:
        """Publish a single envelope. Returns True if Redis accepted the publish."""
        if not self._feature_publish_allowed(feature_id):
            return False

        envelope: dict[str, object] = {
            "schema_version": CLUSTER_ENVELOPE_SCHEMA_VERSION,
            "channel": channel,
            "idempotency_key": uuid.uuid4().hex,
            "emitted_at": datetime.now(UTC).isoformat(),
            "origin": self._origin,
            "payload": payload,
        }
        if feature_id is not None:
            envelope["feature_id"] = feature_id
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

    def _feature_publish_allowed(self, feature_id: str | None) -> bool:
        """Return whether this node may publish an envelope tagged with a feature-ID."""
        if feature_id is None:
            return True
        if not feature_id:
            logger.warning("Cluster publish blocked: feature_id is empty")
            return False

        mark = self._registry.mark_for(feature_id)
        if mark is None:
            logger.warning("Cluster publish blocked: feature_id is not declared", feature_id=feature_id)
            return False
        if not self._registry.carries(feature_id):
            logger.warning("Cluster publish blocked: local node does not carry feature_id", feature_id=feature_id)
            return False
        if mark is FeatureMark.MUST_NEGOTIATE:
            capability_map = self._capability_map_provider() if self._capability_map_provider is not None else None
            if capability_map is None or not capability_map.safe_to_require(feature_id):
                logger.info("Cluster publish held until fleet advertises feature_id", feature_id=feature_id)
                return False
        return True
