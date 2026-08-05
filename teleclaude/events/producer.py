"""Event producer - emit events to the Redis Stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.transport.redis_client import create_redis_client

logger = get_logger(__name__)

# Process-wide singleton producer. The daemon registers one eagerly at startup
# via `configure_producer`; short-lived CLI processes opt in to lazy construction
# at their own boundary by calling `ensure_event_producer`. Loop-local callers use
# `loop_local_producer` so their Redis client cannot outlive its event loop.
_PRODUCER_STATE: dict[str, EventProducer | None] = {"producer": None}


class EventProducer:
    """Publish event envelopes to the configured Redis stream."""

    def __init__(self, redis_client: Any, stream: str = "teleclaude:events", maxlen: int = 10000) -> None:
        self._redis = redis_client
        self._stream = stream
        self._maxlen = maxlen

    async def emit(self, envelope: EventEnvelope) -> str:
        """Serialize and append an event envelope to the Redis stream."""
        if envelope.originating_computer is None:
            envelope.originating_computer = config.computer.name
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

    async def aclose(self) -> None:
        """Close the Redis client and its owned connection pool."""
        await self._redis.aclose()


def configure_producer(producer: EventProducer) -> None:
    """Install the process-wide producer used by `emit_event`."""
    _PRODUCER_STATE["producer"] = producer


def _build_producer_from_config() -> EventProducer:
    """Construct an `EventProducer` from `config.redis` via the shared client factory."""
    redis_cfg = config.redis
    if not redis_cfg.url:
        raise RuntimeError("EventProducer cannot be built: config.redis.url is empty")
    client = create_redis_client(
        redis_cfg.url,
        password=redis_cfg.password,
        max_connections=redis_cfg.max_connections,
        socket_timeout=redis_cfg.socket_timeout,
    )
    return EventProducer(client)


def ensure_event_producer() -> EventProducer:
    """Build and register a producer from `config.redis` when none is configured.

    Intended for short-lived CLI processes that need to publish events but do
    not own the daemon's transport. Idempotent: returns the existing producer
    when one is already registered. Daemon code paths must not call this — the
    daemon's startup is the sole authoritative `configure_producer` site, and
    `emit_event` failing fast on its absence is how startup regressions surface.
    """
    producer = _PRODUCER_STATE["producer"]
    if producer is not None:
        return producer
    producer = _build_producer_from_config()
    _PRODUCER_STATE["producer"] = producer
    return producer


@asynccontextmanager
async def loop_local_producer() -> AsyncIterator[EventProducer]:
    """Yield a producer whose Redis client lives only for the current event loop."""
    producer = _build_producer_from_config()
    try:
        yield producer
    finally:
        await producer.aclose()


async def emit_event(
    event: str,
    source: str,
    level: EventLevel,
    *,
    producer: EventProducer | None = None,
    **kwargs: Any,
) -> str:
    """Build an envelope from explicit fields and publish via the configured producer."""
    if producer is None:
        producer = _PRODUCER_STATE["producer"]
        if producer is None:
            logger.error("emit_event called but EventProducer not configured: event=%s", event)
            raise RuntimeError("EventProducer not configured. Call configure_producer() first.")
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
