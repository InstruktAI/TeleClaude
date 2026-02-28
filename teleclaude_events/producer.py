"""Event producer — emit events to the Redis Stream."""

from __future__ import annotations

from typing import Any

from teleclaude_events.envelope import EventEnvelope, EventLevel, EventVisibility

# Module-level singleton producer — configured by daemon on startup
_producer: "EventProducer | None" = None


class EventProducer:
    def __init__(self, redis_client: Any, stream: str = "teleclaude:events", maxlen: int = 10000) -> None:
        self._redis = redis_client
        self._stream = stream
        self._maxlen = maxlen

    async def emit(self, envelope: EventEnvelope) -> str:
        data = envelope.to_stream_dict()
        entry_id: bytes = await self._redis.xadd(self._stream, data, maxlen=self._maxlen)  # type: ignore[assignment]
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)


def configure_producer(producer: EventProducer) -> None:
    global _producer
    _producer = producer


async def emit_event(
    event: str,
    source: str,
    level: EventLevel,
    domain: str = "",
    description: str = "",
    payload: dict[str, Any] | None = None,
    visibility: EventVisibility = EventVisibility.LOCAL,
    entity: str | None = None,
    **kwargs: Any,
) -> str:
    if _producer is None:
        raise RuntimeError("EventProducer not configured. Call configure_producer() first.")
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
    return await _producer.emit(envelope)
