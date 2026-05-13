"""Visibility-aware internal event bus for TeleClaude.

Events are routed by ``EventVisibility``:

- ``LOCAL`` — dispatched in-process to registered handlers, no Redis hop.
  Used for same-process signalling (e.g. ``AGENT_READY`` between coordinator
  and launcher).
- ``CLUSTER`` (default) — published to Redis Streams for cross-host fan-out
  via the EventProcessor consumer-group path. Same-process subscribers are
  still served through the existing consumer redelivery dedup.

Redis is the cross-host propagation boundary for ``CLUSTER`` events only;
``LOCAL`` events continue to dispatch when Redis is unavailable. Workflow
truth remains in SQLite-owned stores; clients fall back to polling canonical
state when cross-host fan-out is degraded. See
``docs/project/design/architecture-v2/event-bus-transports.md``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict, cast

from instrukt_ai_logging import get_logger
from pydantic import JsonValue

from teleclaude.core.event_guard import create_event_guard
from teleclaude.core.events import (
    AgentAvailabilityContext,
    AgentEventContext,
    AgentEventPayload,
    AgentHookEventType,
    AgentOutputPayload,
    AgentRestartDispatchedPayload,
    AgentSessionStartPayload,
    AgentStopActivityEvent,
    AgentStopPayload,
    ErrorEventContext,
    EventContext,
    EventType,
    JobCompletedPayload,
    JobFailedPayload,
    JobStartedPayload,
    MessageEventContext,
    NotificationClaimedPayload,
    NotificationResolvedPayload,
    OperationCompletedContext,
    SessionCloseCompletedPayload,
    SessionEscalatedPayload,
    SessionLifecycleContext,
    SessionStatusContext,
    SessionTitleChangedContext,
    SessionUpdatedContext,
    SystemCommandContext,
    ToolUseActivityEvent,
    UserPromptSubmitActivityEvent,
    UserPromptSubmitPayload,
)
from teleclaude.events.catalog import EventCatalog
from teleclaude.events.domain_config import AutonomyLevel, AutonomyMatrix, DomainConfig
from teleclaude.events.domain_handlers import DomainHandler, DomainHandlerSpec
from teleclaude.events.domain_pipeline import DomainPipeline, DomainPipelineRunner
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import Pipeline, PipelineContext
from teleclaude.events.processor import EventProcessor

if TYPE_CHECKING:
    from teleclaude.events.db import EventDB

logger = get_logger(__name__)

INTERNAL_EVENT_STREAM = "teleclaude:internal-events"
INTERNAL_EVENT_NAMESPACE_PREFIX = "internal."
_INTERNAL_CONSUMER_GROUP_PREFIX = "event-bus:"
_INTERNAL_EVENT_SOURCE = "event-bus"
_CONTEXT_TYPE_KEY = "context_type"
_INTERNAL_DOMAIN_NAME = "internal-event-bus"
# Live-process redelivery cache cap. The cache drops entries on successful
# deliver() so steady-state size tracks in-flight envelopes. The cap bounds
# pathological growth from envelopes that fail every retry and reach DLQ
# without the bus observing the terminal ACK.
_SUCCESS_CACHE_MAX_KEYS = 1024

EventHandler = Callable[[str, EventContext], Awaitable[object]]
ContextBuilder = Callable[[Mapping[str, JsonValue]], EventContext]


class DispatchEnvelope(TypedDict, total=False):
    status: Literal["success", "error"]
    data: object | None
    error: str
    code: str


class RedisStreamsClient(Protocol):
    """Redis client surface used by the internal event bus."""

    async def xadd(self, stream: str, data: dict[str, str], **kwargs: object) -> bytes | str: ...

    async def xgroup_create(self, stream: str, group: str, **kwargs: object) -> object: ...

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        **kwargs: object,
    ) -> object: ...

    async def xack(self, stream: str, group: str, entry_id: bytes | str) -> object: ...


@dataclass(frozen=True)
class InternalEventBusContract:
    """Structured implementation-boundary contract for internal events."""

    stream_name: str
    consumer_group_rule: str
    event_namespace_rule: str
    redis_outage_mode: str


INTERNAL_EVENT_BUS_CONTRACT = InternalEventBusContract(
    stream_name=INTERNAL_EVENT_STREAM,
    consumer_group_rule=f"{_INTERNAL_CONSUMER_GROUP_PREFIX}{{role}}",
    event_namespace_rule=f"{INTERNAL_EVENT_NAMESPACE_PREFIX}{{event_name}}",
    redis_outage_mode=(
        "Redis is required for internal propagation; Redis outage stops fan-out, "
        "does not mutate SQLite workflow truth, and callers fall back to polling canonical state."
    ),
)


class _InternalEventPipeline:
    """Pipeline adapter used by EventProcessor for internal-event entries."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def execute(self, event: EventEnvelope) -> EventEnvelope | None:
        """Deliver an internal event through the bus subscriber fan-out."""
        return await self._bus.deliver(event)


def _internal_pipeline_context() -> PipelineContext:
    return PipelineContext(
        catalog=cast(EventCatalog, object()),
        db=cast("EventDB", object()),
    )


def decode_internal_event_envelope(envelope: EventEnvelope) -> tuple[str, EventContext]:
    """Decode an internal EventBus envelope into the original event and context."""
    if not envelope.event.startswith(INTERNAL_EVENT_NAMESPACE_PREFIX):
        raise ValueError(f"EventBus cannot decode non-internal event: {envelope.event}")
    event_name = envelope.event.removeprefix(INTERNAL_EVENT_NAMESPACE_PREFIX)
    return event_name, _context_from_payload(envelope.payload)


def _context_from_payload(payload: Mapping[str, JsonValue]) -> EventContext:
    raw_context_type = payload.get(_CONTEXT_TYPE_KEY)
    if not isinstance(raw_context_type, str):
        raise ValueError("EventBus envelope payload is missing context_type")
    builder = _CONTEXT_BUILDERS.get(raw_context_type)
    if builder is None:
        raise ValueError(f"Unsupported EventBus context_type: {raw_context_type}")
    return builder(payload)


def _build_dataclass_context(context_type: type[Any], payload: Mapping[str, JsonValue]) -> EventContext:
    field_names = {field.name for field in dataclasses.fields(context_type)}
    kwargs = {key: value for key, value in payload.items() if key in field_names}
    return cast(EventContext, context_type(**kwargs))


def _build_agent_event_context(payload: Mapping[str, JsonValue]) -> AgentEventContext:
    event_type = _agent_hook_event_type(payload.get("event_type"))
    data = _agent_event_payload(event_type, _required_mapping(payload, "data"))
    return AgentEventContext(
        session_id=_required_str(payload, "session_id"),
        data=data,
        event_type=event_type,
    )


def _agent_event_payload(event_type: AgentHookEventType, payload: Mapping[str, JsonValue]) -> AgentEventPayload:
    if event_type == "session_start":
        return AgentSessionStartPayload(
            raw=_optional_mapping(payload.get("raw")),
            transcript_path=_optional_str(payload.get("transcript_path")),
            session_id=_optional_str(payload.get("session_id")),
        )
    if event_type == "user_prompt_submit":
        return UserPromptSubmitPayload(
            prompt=_required_str(payload, "prompt"),
            session_id=_optional_str(payload.get("session_id")),
            transcript_path=_optional_str(payload.get("transcript_path")),
            raw=_optional_mapping(payload.get("raw")),
            source_computer=_optional_str(payload.get("source_computer")),
        )
    if event_type == "agent_stop":
        return AgentStopPayload(
            session_id=_optional_str(payload.get("session_id")),
            transcript_path=_optional_str(payload.get("transcript_path")),
            prompt=_optional_str(payload.get("prompt")),
            raw=_optional_mapping(payload.get("raw")),
            source_computer=_optional_str(payload.get("source_computer")),
        )
    if event_type == "tool_use":
        return AgentOutputPayload(
            session_id=_optional_str(payload.get("session_id")),
            transcript_path=_optional_str(payload.get("transcript_path")),
            raw=_optional_mapping(payload.get("raw")),
            source_computer=_optional_str(payload.get("source_computer")),
        )
    raise ValueError(f"Unsupported agent event_type: {event_type}")


def _agent_hook_event_type(value: JsonValue | None) -> AgentHookEventType:
    if value in {"agent_stop", "session_start", "tool_use", "user_prompt_submit"}:
        return cast(AgentHookEventType, value)
    raise ValueError(f"Unsupported agent hook event_type: {value!r}")


def _required_mapping(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    return _mapping_value(payload.get(key), field_name=key)


def _optional_mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    if value is None:
        return {}
    return _mapping_value(value, field_name="mapping")


def _mapping_value(value: JsonValue | None, *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected mapping for {field_name}")
    return cast(Mapping[str, JsonValue], value)


def _required_str(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise ValueError(f"Expected string for {key}")


def _optional_str(value: JsonValue | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"Expected optional string, got {value!r}")


_CONTEXT_BUILDERS: Mapping[str, ContextBuilder] = {
    "AgentAvailabilityContext": lambda payload: _build_dataclass_context(AgentAvailabilityContext, payload),
    "AgentEventContext": _build_agent_event_context,
    "AgentRestartDispatchedPayload": lambda payload: _build_dataclass_context(AgentRestartDispatchedPayload, payload),
    "AgentStopActivityEvent": lambda payload: _build_dataclass_context(AgentStopActivityEvent, payload),
    "ErrorEventContext": lambda payload: _build_dataclass_context(ErrorEventContext, payload),
    "JobCompletedPayload": lambda payload: _build_dataclass_context(JobCompletedPayload, payload),
    "JobFailedPayload": lambda payload: _build_dataclass_context(JobFailedPayload, payload),
    "JobStartedPayload": lambda payload: _build_dataclass_context(JobStartedPayload, payload),
    "MessageEventContext": lambda payload: _build_dataclass_context(MessageEventContext, payload),
    "NotificationClaimedPayload": lambda payload: _build_dataclass_context(NotificationClaimedPayload, payload),
    "NotificationResolvedPayload": lambda payload: _build_dataclass_context(NotificationResolvedPayload, payload),
    "OperationCompletedContext": lambda payload: _build_dataclass_context(OperationCompletedContext, payload),
    "SessionCloseCompletedPayload": lambda payload: _build_dataclass_context(SessionCloseCompletedPayload, payload),
    "SessionEscalatedPayload": lambda payload: _build_dataclass_context(SessionEscalatedPayload, payload),
    "SessionLifecycleContext": lambda payload: _build_dataclass_context(SessionLifecycleContext, payload),
    "SessionStatusContext": lambda payload: _build_dataclass_context(SessionStatusContext, payload),
    "SessionTitleChangedContext": lambda payload: _build_dataclass_context(SessionTitleChangedContext, payload),
    "SessionUpdatedContext": lambda payload: _build_dataclass_context(SessionUpdatedContext, payload),
    "SystemCommandContext": lambda payload: _build_dataclass_context(SystemCommandContext, payload),
    "ToolUseActivityEvent": lambda payload: _build_dataclass_context(ToolUseActivityEvent, payload),
    "UserPromptSubmitActivityEvent": lambda payload: _build_dataclass_context(UserPromptSubmitActivityEvent, payload),
}


class EventBus:
    """Redis Streams-backed event bus for core internal events."""

    def __init__(self, *, role: str = "unconfigured", redis_client: RedisStreamsClient | None = None) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pending_tasks: set[asyncio.Task[str]] = set()
        self._successful_handlers: dict[str, set[int]] = {}
        self._role = role
        self._redis = redis_client

    def subscribe(self, event: EventType, handler: EventHandler) -> EventHandler:
        """Subscribe a handler to an event. Returns the registered (wrapped) handler.

        The returned reference is the handle to pass to ``unsubscribe`` — the bus
        wraps every handler in an error guard, and only the wrapped version is
        stored on the dispatch list, so unsubscribing by the original callable
        would never match.
        """
        if event not in self._handlers:
            self._handlers[event] = []
        wrapped = create_event_guard(handler, emit=self.emit, reraise=True)
        self._handlers[event].append(wrapped)
        logger.debug("Subscribed handler for event: %s (total: %d)", event, len(self._handlers[event]))
        return wrapped

    def unsubscribe(self, event: EventType, wrapped_handler: EventHandler) -> None:
        """Remove a handler previously returned by ``subscribe``. Idempotent."""
        handlers = self._handlers.get(event)
        if not handlers:
            return
        try:
            handlers.remove(wrapped_handler)
        except ValueError:
            return
        logger.debug("Unsubscribed handler for event: %s (remaining: %d)", event, len(handlers))

    def clear(self) -> None:
        """Clear all registered handlers (primarily for tests)."""
        self._handlers.clear()
        self._successful_handlers.clear()

    def configure(self, *, role: str, redis_client: RedisStreamsClient) -> None:
        """Bind the bus to a process role and Redis client."""
        self._role = role
        self._redis = redis_client

    def emit(
        self,
        event: EventType,
        context: EventContext,
        *,
        visibility: EventVisibility = EventVisibility.CLUSTER,
    ) -> Awaitable[str]:
        """Publish an internal event and return the scheduled task.

        ``visibility=LOCAL`` dispatches handlers in-process and never touches
        Redis. Use it for intra-process signalling (e.g. ``AGENT_READY`` between
        coordinator and launcher) so that high-volume same-process events do
        not consume the Redis connection pool.

        ``visibility=CLUSTER`` (default) publishes the envelope to Redis Streams
        for cross-host fan-out via the EventProcessor consumer-group path —
        existing behavior preserved for back-compat.
        """
        loop = asyncio.get_running_loop()
        if visibility == EventVisibility.LOCAL:
            task = loop.create_task(
                self._dispatch_local(event, context),
                name=f"event-bus-local-{event}",
            )
        else:
            task = loop.create_task(self._publish(event, context), name=f"event-bus-publish-{event}")
        self._pending_tasks.add(task)
        task.add_done_callback(self._publish_done)
        return task

    async def _dispatch_local(self, event: str, context: EventContext) -> str:
        """Synchronously dispatch the event to in-process subscribers.

        Mirrors the same (event_name, context) call shape that the Redis
        consumer-group path produces via ``_subscriber_process``. Errors in
        individual handlers are logged and do not propagate, matching the
        existing event-guard contract for cluster delivery.
        """
        handlers = list(self._handlers.get(event, []))
        for handler in handlers:
            try:
                await handler(event, context)
            except Exception:
                logger.exception("EventBus local dispatch handler failed event=%s", event)
        return "local"

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Consume internal events through the shared EventProcessor loop."""
        if self._redis is None:
            raise RuntimeError("EventBus.start requires a configured Redis client")

        processor = EventProcessor(
            self._redis,
            cast(Pipeline, _InternalEventPipeline(self)),
            stream=INTERNAL_EVENT_STREAM,
            group=self._consumer_group(),
            consumer_name=self._consumer_name(),
        )
        await processor.start(shutdown_event)

    async def deliver(self, envelope: EventEnvelope) -> EventEnvelope | None:
        """Run matching local subscribers under the EventProcessor ACK boundary."""
        specs = self._subscriber_specs()
        if not specs:
            decode_internal_event_envelope(envelope)
            return envelope

        runner = DomainPipelineRunner()
        runner.register_domain_pipeline(
            _INTERNAL_DOMAIN_NAME,
            DomainPipeline(
                domain=DomainConfig(
                    name=_INTERNAL_DOMAIN_NAME,
                    autonomy=AutonomyMatrix(global_default=AutonomyLevel.AUTONOMOUS),
                ),
                levels=[specs],
            ),
        )
        results = await runner.run_all(envelope, _internal_pipeline_context())
        # All level handlers succeeded or skipped — the EventProcessor will ACK
        # this entry and never redeliver it, so the per-handler success ledger
        # for this envelope can be released. On exception, run_all re-raises and
        # this line is skipped so retries still see prior successes as cache hits.
        if envelope.idempotency_key is not None:
            self._successful_handlers.pop(envelope.idempotency_key, None)
        return results.get(_INTERNAL_DOMAIN_NAME)

    async def _publish(self, event: str, context: EventContext) -> str:
        if self._redis is None:
            raise RuntimeError("EventBus.emit requires a configured Redis client")

        envelope = EventEnvelope(
            event=self._wire_event_name(event),
            source=f"{_INTERNAL_EVENT_SOURCE}:{self._role}",
            level=EventLevel.WORKFLOW,
            domain="internal",
            visibility=EventVisibility.CLUSTER,
            payload=self._context_payload(context),
            idempotency_key=str(uuid.uuid4()),
        )
        entry_id = await self._redis.xadd(INTERNAL_EVENT_STREAM, envelope.to_stream_dict(), maxlen=10000)
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    def _publish_done(self, task: asyncio.Task[str]) -> None:
        self._pending_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("EventBus Redis publish failed")

    def _consumer_group(self) -> str:
        return f"{_INTERNAL_CONSUMER_GROUP_PREFIX}{self._role}"

    def _consumer_name(self) -> str:
        return f"{self._role}:{os.getpid()}:{id(self)}"

    def _wire_event_name(self, event: str) -> str:
        return f"{INTERNAL_EVENT_NAMESPACE_PREFIX}{event}"

    def _subscriber_specs(self) -> list[DomainHandlerSpec]:
        specs: list[DomainHandlerSpec] = []
        for event_name, handlers in self._handlers.items():
            for index, handler in enumerate(handlers):
                specs.append(
                    DomainHandlerSpec(
                        handler_id=f"{event_name}:{index}",
                        process=self._subscriber_process(event_name, handler),
                    )
                )
        return specs

    def _subscriber_process(self, subscribed_event: str, handler: EventHandler) -> DomainHandler:
        async def _process(envelope: EventEnvelope, _context: PipelineContext) -> EventEnvelope | None:
            event_name, context = decode_internal_event_envelope(envelope)
            if event_name != subscribed_event:
                return envelope
            cache_key = envelope.idempotency_key
            handler_id = id(handler)
            if cache_key is not None and handler_id in self._successful_handlers.get(cache_key, ()):
                return None
            result = await handler(event_name, context)
            if cache_key is not None:
                self._record_handler_success(cache_key, handler_id)
            return envelope if result is not None else None

        return _process

    def _record_handler_success(self, idempotency_key: str, handler_id: int) -> None:
        bucket = self._successful_handlers.get(idempotency_key)
        if bucket is None:
            self._successful_handlers[idempotency_key] = {handler_id}
        else:
            bucket.add(handler_id)
        # FIFO cap on retained idempotency keys (relies on dict insertion order).
        # Bounds pathological growth from envelopes that DLQ without the bus
        # observing the terminal ACK; live-process success cleanup happens in
        # deliver() after run_all succeeds.
        while len(self._successful_handlers) > _SUCCESS_CACHE_MAX_KEYS:
            evicted = next(iter(self._successful_handlers))
            self._successful_handlers.pop(evicted, None)

    def _context_payload(self, context: EventContext) -> dict[str, JsonValue]:
        payload = _json_object(context)
        payload[_CONTEXT_TYPE_KEY] = type(context).__name__
        return payload


def _json_object(value: object) -> dict[str, JsonValue]:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        raw_mapping = cast(Mapping[object, object], value)
        return {str(key): _json_value(item) for key, item in raw_mapping.items()}
    raise TypeError(f"Expected dataclass or mapping for EventBus payload, got {type(value).__name__}")


def _json_value(value: object) -> JsonValue:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_object(value)
    if isinstance(value, Mapping):
        return _json_object(value)
    if isinstance(value, datetime):
        return _datetime_value(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    raise TypeError(f"Unsupported EventBus payload value: {type(value).__name__}")


def _datetime_value(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def configure_event_bus(*, role: str, redis_client: RedisStreamsClient) -> EventBus:
    """Configure the process-wide EventBus singleton without clearing subscriptions."""
    event_bus.configure(role=role, redis_client=redis_client)
    return event_bus


event_bus = EventBus()
