"""Event producer — the emission boundary that publishes typed events to the platform stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.config.machine import config
from teleclaude.core.inbound.fleet import contraction_answer_from_heartbeats
from teleclaude.core.internal_event_envelope import INTERNAL_EVENT_STREAM
from teleclaude.core.models import JsonDict
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.reconciliation import (
    DOMAIN_EVENT_DELIVERY_FEATURE_ID,
    INCIDENT_ALERTS_FEATURE_ID,
    ContractionAnswer,
)
from teleclaude.events.catalog import PlatformEvent
from teleclaude.events.envelope import (
    EventHome,
    ReceivedEvent,
)
from teleclaude.events.envelope_facts import EnvelopeFactResolver, cli_envelope_fact_resolver, home_owner_of
from teleclaude.events.references import EventRef, InboundSourceRef, SessionRef
from teleclaude.events.scope import EventScope, ScopedClients, scope_of
from teleclaude.events.scoped_redis import close_scoped_clients, scoped_redis_clients
from teleclaude.events.wire import LegacyFacts, StreamEvent, encode
from teleclaude.transport.internal_event_compat import encode_internal_compatibility

logger = get_logger(__name__)

# The public platform stream is the default for existing producer callers.
DEFAULT_EVENT_STREAM = "teleclaude:events"
# Claim the delivery and append it in one step, so a claim never stands without its event (ADR-0148).
_CLAIM_AND_APPEND_SCRIPT = """
if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[1]) then
  return false
end
local command = {'XADD', KEYS[1], 'MAXLEN', '~', ARGV[2], '*'}
for index = 3, #ARGV do
  command[#command + 1] = ARGV[index]
end
return redis.call(unpack(command))
"""
_CLAIM_KEY_TEMPLATE = "teleclaude:ingress:claim:{identity}"
_PRODUCER_MISSING_EVENT_TEMPLATE = "event emitted but EventProducer not configured: event=%s stream=%s"
_PRODUCER_NOT_CONFIGURED_TEMPLATE = "EventProducer not configured for stream {stream}. Call configure_producer() first."
_CONFIGURED_PRODUCER_ACCESS_EVENT = "configured producer access"
_REDIS_UNCONFIGURED_ERROR = "EventProducer cannot be built: config.redis.cluster.url is empty"

# Process-wide producers by source stream. The daemon registers them at startup,
# via `configure_producer`; short-lived CLI processes opt in to lazy construction
# at their own boundary by calling `ensure_event_producer`. Loop-local callers use
# `loop_local_producer` so their Redis client cannot outlive its event loop.
_PRODUCER_STATE: dict[str, EventProducer] = {}


class RelayedEvent(BaseModel):
    """An event relayed from an external system through a declared inbound source.

    Its type and data are the source's own, not a platform catalog declaration:
    the inbound endpoint translates the request into this one event shape and
    states the declared source as the subject and the declaring home as the home.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    type: str
    subject: InboundSourceRef
    home: EventHome
    data: JsonDict
    time: datetime | None = None


class EventProducer:
    """Publish events to their stream on the Redis of their scope."""

    def __init__(
        self,
        redis_clients: ScopedClients[Any],
        fact_resolver: EnvelopeFactResolver,
        contraction_answer: ContractionAnswer | None = None,
        stream: str = DEFAULT_EVENT_STREAM,
        maxlen: int = 10000,
    ) -> None:
        self._clients = redis_clients
        self._fact_resolver = fact_resolver
        self._contraction_answer = contraction_answer
        self._stream = stream
        self._maxlen = maxlen

    async def emit(self, event: PlatformEvent[Any, Any] | RelayedEvent, legacy: LegacyFacts, /) -> str:
        """Complete the event with the boundary's facts, serialize it, and append it to the stream.

        The boundary adds the source, the time, the caller session and the project owner, and an
        id when the producer states none. It refuses, alters and narrows nothing on the strength
        of the facts the producer stated.
        """
        received = self._received_event(event)
        omit_notification_facts = await self._notification_facts_unread()
        entry = encode(received, legacy, omit_notification_facts=omit_notification_facts)
        scope = EventScope.CLUSTER if isinstance(event, RelayedEvent) else scope_of(received.type)
        return await self._append(received.type, entry, received.subject, scope)

    async def emit_once(self, event: RelayedEvent, legacy: LegacyFacts, /, *, claim: str, ttl_s: int) -> str | None:
        """Append a relayed event only when ``claim`` is new, claiming it in the same atomic step.

        Returns the stream entry id, or ``None`` when the claim was already taken, which means another
        receipt of the same delivery has relayed it. The claim is kept for ``ttl_s`` seconds.
        """
        received = self._received_event(event)
        omit_notification_facts = await self._notification_facts_unread()
        entry = encode(received, legacy, omit_notification_facts=omit_notification_facts)
        client = self._clients.for_scope(EventScope.CLUSTER)
        fields = [part for pair in entry.items() for part in pair]
        try:
            entry_id = await client.eval(
                _CLAIM_AND_APPEND_SCRIPT,
                2,
                self._stream,
                _CLAIM_KEY_TEMPLATE.format(identity=claim),
                ttl_s,
                self._maxlen,
                *fields,
            )
        except Exception:
            logger.exception("EventProducer.emit_once FAILED: event=%s", received.type)
            raise
        if entry_id is None:
            logger.info("EventProducer.emit_once duplicate: event=%s claim=%s", received.type, claim)
            return None
        result = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        logger.info("EventProducer.emit_once OK: event=%s entry_id=%s", received.type, result)
        return result

    async def emit_internal(self, event: PlatformEvent[Any, Any], legacy: LegacyFacts, /) -> str:
        """Append a typed runtime fact with its earlier wire form while the fleet still requires it."""
        if self._stream != INTERNAL_EVENT_STREAM:
            raise RuntimeError("Runtime event publication requires the internal stream producer")
        received = self._received_event(event)
        omit_notification_facts = await self._notification_facts_unread()
        entry = encode(received, legacy, omit_notification_facts=omit_notification_facts)
        if not await self._feature_is_contracted(DOMAIN_EVENT_DELIVERY_FEATURE_ID):
            entry = encode_internal_compatibility(received, entry, legacy)
        return await self._append(received.type, entry, received.subject, scope_of(received.type))

    async def _notification_facts_unread(self) -> bool:
        """Whether the fleet answers, now, that no live computer reads an event's notification facts."""
        return await self._feature_is_contracted(INCIDENT_ALERTS_FEATURE_ID)

    async def _feature_is_contracted(self, feature_id: str) -> bool:
        """Fail closed when the live fleet answer is not available."""
        if self._contraction_answer is None:
            return False
        return await self._contraction_answer(feature_id)

    def _received_event(self, event: PlatformEvent[Any, Any] | RelayedEvent) -> ReceivedEvent:
        """Add the facts only the boundary knows: source, time, caller session, project owner, and an id."""
        resolver = self._fact_resolver
        session_id = get_caller_session_id() or resolver.session_id()
        if isinstance(event, RelayedEvent):
            return ReceivedEvent(
                id=str(uuid4()),
                type=event.type,
                source=config.computer.name,
                subject=event.subject.to_ref(),
                time=event.time or datetime.now(UTC),
                data=event.data,
                home=event.home,
                home_owner=home_owner_of(event.home, resolver),
            )
        related = [reference.to_ref() for reference in event.related]
        session = SessionRef(session_id).to_ref() if session_id else None
        if session is not None and session not in related:
            related.append(session)
        return ReceivedEvent(
            id=event.id or str(uuid4()),
            type=event.type_name(),
            source=config.computer.name,
            subject=event.subject.to_ref(),
            time=datetime.now(UTC),
            data=event.data.model_dump(mode="json"),
            home=event.home,
            home_owner=home_owner_of(event.home, resolver),
            related=tuple(related),
            causationid=event.causationid,
        )

    def stage(self, event: PlatformEvent[Any, Any] | RelayedEvent, legacy: LegacyFacts) -> StreamEvent:
        """Complete an event as the stream would deliver it, without publishing it."""
        return StreamEvent.model_validate({**dict(self._received_event(event)), "legacy": legacy})

    async def _append(self, event_type: str, entry: dict[str, str], subject: EventRef | None, scope: EventScope) -> str:
        logger.info(
            "EventProducer.emit: event=%s subject=%s stream=%s",
            event_type,
            subject.to_token() if subject is not None else "",
            self._stream,
        )
        try:
            client = self._clients.for_scope(scope)
            entry_id = await client.xadd(self._stream, entry, maxlen=self._maxlen)
        except Exception:
            logger.exception("EventProducer.emit xadd FAILED: event=%s", event_type)
            raise
        result = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        logger.info("EventProducer.emit OK: event=%s entry_id=%s", event_type, result)
        return result

    def stream_name(self) -> str:
        """Return the Redis stream used by this producer."""
        return self._stream

    async def aclose(self) -> None:
        """Close every Redis client and its owned connection pool, each even when an earlier close failed."""
        await close_scoped_clients(self._clients)


def configure_producer(producer: EventProducer) -> None:
    """Install the process-wide producer for its declared stream."""
    _PRODUCER_STATE[producer.stream_name()] = producer


def _build_producer_from_config(stream: str = DEFAULT_EVENT_STREAM) -> EventProducer:
    """Construct an `EventProducer` from `config.redis`, with a client of each scope's Redis."""
    if not config.redis.cluster.url:
        raise RuntimeError(_REDIS_UNCONFIGURED_ERROR)
    return EventProducer(
        scoped_redis_clients(), cli_envelope_fact_resolver(), contraction_answer_from_heartbeats, stream=stream
    )


def ensure_event_producer() -> EventProducer:
    """Build and register a producer from `config.redis` when none is configured.

    Intended for short-lived CLI processes that need to publish events but do
    not own the daemon's transport. Idempotent: returns the existing producer
    when one is already registered. Daemon code paths must not call this — the
    daemon's startup is the sole authoritative `configure_producer` site, and
    `publish_event` failing fast on its absence is how startup regressions surface.
    """
    producer = _PRODUCER_STATE.get(DEFAULT_EVENT_STREAM)
    if producer is not None:
        return producer
    producer = _build_producer_from_config()
    configure_producer(producer)
    return producer


@asynccontextmanager
async def loop_local_producer() -> AsyncIterator[EventProducer]:
    """Yield a producer whose Redis client lives only for the current event loop."""
    producer = _build_producer_from_config()
    try:
        yield producer
    finally:
        await producer.aclose()


def _configured_producer(stream: str, event_name: str) -> EventProducer:
    producer = _PRODUCER_STATE.get(stream)
    if producer is None:
        logger.error(_PRODUCER_MISSING_EVENT_TEMPLATE, event_name, stream)
        raise RuntimeError(_PRODUCER_NOT_CONFIGURED_TEMPLATE.format(stream=stream))
    return producer


def configured_producer(stream: str = DEFAULT_EVENT_STREAM) -> EventProducer:
    """Return the daemon-composed producer for one stream without fallback construction."""
    return _configured_producer(stream, _CONFIGURED_PRODUCER_ACCESS_EVENT)


async def publish_event(
    event: PlatformEvent[Any, Any],
    legacy: LegacyFacts,
    *,
    producer: EventProducer | None = None,
) -> str:
    """Publish a typed event through the configured producer."""
    target = producer if producer is not None else _configured_producer(DEFAULT_EVENT_STREAM, event.type_name())
    return await target.emit(event, legacy)
