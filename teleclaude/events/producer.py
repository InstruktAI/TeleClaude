"""Event producer — emit events to the Redis Stream."""

from __future__ import annotations

from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

logger = get_logger(__name__)

# Module-level singleton producer — configured by daemon on startup
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


async def emit_event(event: str, source: str, level: EventLevel, **kwargs: Any) -> str:
    """Build an envelope from explicit fields and publish it via the configured producer."""
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
