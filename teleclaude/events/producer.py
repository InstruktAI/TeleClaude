"""Event producer - emit events to the Redis Stream."""

from __future__ import annotations

import ssl
from typing import Any

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.config import config
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

logger = get_logger(__name__)

# Process-wide singleton producer. The daemon registers one eagerly at startup;
# CLI invocations build one lazily via `ensure_event_producer` so they can publish
# to the same Redis stream the daemon polls.
_PRODUCER_STATE: dict[str, EventProducer | None] = {"producer": None}


class EventProducer:
    """Publish event envelopes to the configured Redis stream."""

    def __init__(self, redis_client: Any, stream: str = "teleclaude:events", maxlen: int = 10000) -> None:
        self._redis = redis_client
        self._stream = stream
        self._maxlen = maxlen

    async def emit(self, envelope: EventEnvelope) -> str:
        """Serialize and append an event envelope to the Redis stream."""
        data = envelope.to_stream_dict()
        logger.info(
            "EventProducer.emit: event=%s entity=%s stream=%s",
            envelope.event,
            envelope.entity or "",
            self._stream,
        )
        try:
            entry_id = await self._redis.xadd(self._stream, data, maxlen=self._maxlen)
        except Exception:
            logger.exception("EventProducer.emit xadd FAILED: event=%s", envelope.event)
            raise
        result = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        logger.info("EventProducer.emit OK: event=%s entry_id=%s", envelope.event, result)
        return result

    def stream_name(self) -> str:
        """Return the Redis stream used by this producer."""
        return self._stream


def configure_producer(producer: EventProducer) -> None:
    """Install the process-wide producer used by `emit_event`."""
    _PRODUCER_STATE["producer"] = producer


def _build_producer_from_config() -> EventProducer:
    """Construct an `EventProducer` against the configured Redis URL."""
    redis_cfg = config.redis
    if not redis_cfg.url:
        raise RuntimeError("EventProducer cannot be built: config.redis.url is empty")
    if redis_cfg.url.startswith("rediss://"):
        client = Redis.from_url(
            redis_cfg.url,
            password=redis_cfg.password,
            decode_responses=False,
            ssl_cert_reqs=ssl.CERT_NONE,
        )
    else:
        client = Redis.from_url(
            redis_cfg.url,
            password=redis_cfg.password,
            decode_responses=False,
        )
    return EventProducer(client)


def ensure_event_producer() -> EventProducer:
    """Return the configured producer, building one from config if needed.

    The daemon pre-registers a producer at startup that wraps its long-lived
    transport client; lazy construction covers short-lived CLI processes that
    publish to the same stream without owning the daemon's transport.
    """
    producer = _PRODUCER_STATE["producer"]
    if producer is not None:
        return producer
    producer = _build_producer_from_config()
    _PRODUCER_STATE["producer"] = producer
    return producer


async def emit_event(event: str, source: str, level: EventLevel, **kwargs: Any) -> str:
    """Build an envelope from explicit fields and publish it via the configured producer."""
    producer = ensure_event_producer()
    domain = str(kwargs.pop("domain", ""))
    description = str(kwargs.pop("description", ""))
    payload = kwargs.pop("payload", None)
    visibility = kwargs.pop("visibility", EventVisibility.LOCAL)
    entity = kwargs.pop("entity", None)
    envelope = EventEnvelope(
        event=event,
        source=source,
        level=level,
        domain=domain,
        description=description,
        payload=payload or {},
        visibility=visibility,
        entity=entity,
        **kwargs,
    )
    return await producer.emit(envelope)
