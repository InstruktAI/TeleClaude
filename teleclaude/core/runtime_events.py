"""Typed publication of agent-runtime facts to its internal event stream."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import uuid4

from teleclaude.config.machine import config
from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.events import AgentHookEventType
from teleclaude.core.internal_event_envelope import INTERNAL_EVENT_STREAM
from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventHome, EventHomeMarker, EventLevel, EventVisibility, occurrence_id
from teleclaude.events.producer import EventProducer, configured_producer
from teleclaude.events.references import ComputerRef, EventRef, OperationRef, SessionRef
from teleclaude.events.schemas.system import (
    RuntimeAgentActivityData,
    RuntimeAgentActivityObserved,
    RuntimeAgentAvailabilityChanged,
    RuntimeAgentAvailabilityData,
    RuntimeErrorData,
    RuntimeErrorReported,
    RuntimeOperationFailed,
    RuntimeOperationOutcomeData,
    RuntimeOperationResult,
    RuntimeOperationSucceeded,
    RuntimeSessionChange,
    RuntimeSessionSourceChanged,
    RuntimeSessionSourceChangedData,
    RuntimeSessionStatusChanged,
    RuntimeSessionStatusData,
)
from teleclaude.events.wire import LegacyFacts

_INTERNAL_STREAM = INTERNAL_EVENT_STREAM
INTERNAL_RUNTIME_EVENT_STREAM = _INTERNAL_STREAM
_INTERNAL_STREAM_REQUIRED = "Runtime event publication requires the internal stream producer"
_RUNTIME_PRODUCER = "agent-runtime"
_DEFAULT_HOME = EventHomeMarker.UNKNOWN


def _legacy_facts(event_id: str) -> LegacyFacts:
    return LegacyFacts(
        producer=_RUNTIME_PRODUCER,
        level=EventLevel.WORKFLOW,
        visibility=EventVisibility.CLUSTER,
        idempotency_key=event_id,
    )


def _require_internal_stream(producer: EventProducer) -> EventProducer:
    if producer.stream_name() != _INTERNAL_STREAM:
        raise RuntimeError(_INTERNAL_STREAM_REQUIRED)
    return producer


def _runtime_producer(producer: EventProducer | None) -> EventProducer:
    return _require_internal_stream(producer or configured_producer(_INTERNAL_STREAM))


async def publish_session_source_change(
    session_id: str,
    change: RuntimeSessionChange,
    *,
    changed_fields: tuple[str, ...] = (),
    home: EventHome = _DEFAULT_HOME,
    producer: EventProducer | None = None,
) -> str:
    """Publish a session source invalidation with one occurrence identity."""
    target = _runtime_producer(producer)
    event_id = str(uuid4())
    event = RuntimeSessionSourceChanged(
        id=event_id,
        subject=SessionRef(session_id),
        home=home,
        data=RuntimeSessionSourceChangedData(
            session_id=session_id,
            change=change,
            changed_fields=list(changed_fields),
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))


async def publish_session_status(
    session_id: str,
    status: str,
    reason: str,
    timestamp: str,
    *,
    last_activity_at: str | None = None,
    message_intent: str | None = None,
    delivery_scope: str | None = None,
    home: EventHome = _DEFAULT_HOME,
    producer: EventProducer | None = None,
) -> str:
    """Publish one canonical runtime status occurrence."""
    target = _runtime_producer(producer)
    event_id = str(uuid4())
    event = RuntimeSessionStatusChanged(
        id=event_id,
        subject=SessionRef(session_id),
        home=home,
        data=RuntimeSessionStatusData(
            session_id=session_id,
            status=status,
            reason=reason,
            timestamp=timestamp,
            last_activity_at=last_activity_at,
            message_intent=message_intent,
            delivery_scope=delivery_scope,
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))


async def publish_agent_activity(
    session_id: str,
    event_type: AgentHookEventType,
    *,
    timestamp: str | None = None,
    canonical_type: str | None = None,
    message_intent: str | None = None,
    delivery_scope: str | None = None,
    details: JsonDict | None = None,
    home: EventHome = _DEFAULT_HOME,
    producer: EventProducer | None = None,
) -> str:
    """Publish one normalized agent-activity occurrence."""
    target = _runtime_producer(producer)
    event_id = str(uuid4())
    event = RuntimeAgentActivityObserved(
        id=event_id,
        subject=SessionRef(session_id),
        home=home,
        data=RuntimeAgentActivityData(
            session_id=session_id,
            event_type=event_type,
            timestamp=timestamp,
            canonical_type=canonical_type,
            message_intent=message_intent,
            delivery_scope=delivery_scope,
            details=details or {},
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))


async def publish_agent_availability(
    computer: str,
    agent: str,
    *,
    status: AgentAvailabilityStatus | None = None,
    status_until: str | None = None,
    reason: str | None = None,
    error: str | None = None,
    model: str | None = None,
    model_status: AgentAvailabilityStatus | None = None,
    model_status_until: str | None = None,
    model_reason: str | None = None,
    producer: EventProducer | None = None,
) -> str:
    """Publish an availability observation for this computer."""
    target = _runtime_producer(producer)
    event_id = str(uuid4())
    event = RuntimeAgentAvailabilityChanged(
        id=event_id,
        subject=ComputerRef(computer),
        home=EventHomeMarker.NONE,
        data=RuntimeAgentAvailabilityData(
            agent=agent,
            status=status,
            status_until=status_until,
            reason=reason,
            error=error,
            model=model,
            model_status=model_status,
            model_status_until=model_status_until,
            model_reason=model_reason,
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))


async def publish_runtime_error(
    source: str | None,
    message: str,
    *,
    event_id: str | None = None,
    session_id: str | None = None,
    details: Mapping[str, object] | None = None,
    severity: str = "error",
    retryable: bool = False,
    code: str | None = None,
    producer: EventProducer | None = None,
) -> str:
    """Publish an error observation without broadening its existing payload reach."""
    target = _runtime_producer(producer)
    event_id = event_id if event_id is not None else str(uuid4())
    subject = SessionRef(session_id).to_ref() if session_id else ComputerRef(config.computer.name).to_ref()
    related = (SessionRef(session_id),) if session_id else ()
    event = RuntimeErrorReported(
        id=event_id,
        subject=EventRef(kind=subject.kind, identity=subject.identity),
        related=related,
        home=EventHomeMarker.UNKNOWN,
        data=RuntimeErrorData(
            session_id=session_id,
            message=message,
            source=source,
            details=cast(JsonDict, dict(details)) if details is not None else None,
            severity=severity,
            retryable=retryable,
            code=code,
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))


async def publish_operation_outcome(
    operation_id: str,
    operation_kind: str,
    result: RuntimeOperationResult,
    *,
    home: EventHome,
    error: str | None = None,
    producer: EventProducer | None = None,
) -> str:
    """Publish an outcome whose identity is stable for the operation's terminal occurrence."""
    target = _runtime_producer(producer)
    event_id = occurrence_id(operation_id, result.value)
    event_type = RuntimeOperationSucceeded if result is RuntimeOperationResult.COMPLETED else RuntimeOperationFailed
    event = event_type(
        id=event_id,
        subject=OperationRef(operation_id),
        home=home,
        data=RuntimeOperationOutcomeData(
            operation_id=operation_id,
            operation_kind=operation_kind,
            error=error,
        ),
    )
    return await target.emit_internal(event, _legacy_facts(event_id))
