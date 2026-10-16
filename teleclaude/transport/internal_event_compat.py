"""Transport-only codec for the retired internal wire and its one-append compatibility form."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, JsonValue

from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.events import (
    ALL_AGENT_HOOK_EVENTS,
    AgentEventContext,
    AgentEventPayload,
    AgentHookEvents,
    AgentHookEventType,
    DeliveryNoComposerContext,
    ErrorEventContext,
    ProjectRefreshTrigger,
    SessionOutputStoppedPayload,
    SystemCommandContext,
    build_agent_payload,
)
from teleclaude.core.internal_event_envelope import (
    INTERNAL_EVENT_STREAM,
    INTERNAL_STREAM_VERSION,
    InternalEventEnvelope,
)
from teleclaude.core.models import JsonDict
from teleclaude.core.operations._kinds import kind_for_outcome_event, outcome_events_for
from teleclaude.events.envelope import (
    EventHomeMarker,
    EventLevel,
    ReceivedEvent,
    occurrence_id,
)
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.events.references import ComputerRef, EventRef, OperationRef, SessionRef
from teleclaude.events.schemas.system import (
    RuntimeAgentActivityData,
    RuntimeAgentActivityObserved,
    RuntimeAgentAvailabilityData,
    RuntimeErrorData,
    RuntimeOperationFailed,
    RuntimeOperationOutcomeData,
    RuntimeOperationSucceeded,
    RuntimeSessionChange,
    RuntimeSessionSourceChanged,
    RuntimeSessionSourceChangedData,
    RuntimeSessionStatusChanged,
    RuntimeSessionStatusData,
)
from teleclaude.events.wire import EntryCodec, LegacyFacts, StreamEvent
from teleclaude.events.wire import decode as decode_platform_event
from teleclaude.runtime.environment import (
    COMPACTION_LAUNCH_CONTEXT_FIELD,
    CompactionLaunchContext,
    decode_compaction_launch_context,
)

INTERNAL_EVENT_NAMESPACE_PREFIX = "internal."
INTERNAL_COMPAT_INGRESS_TYPE = "teleclaude.internal.compat.ingress"
_CONTEXT_TYPE_KEY = "context_type"
_EMPTY = ""
_NO_HOME = "none"
_EVENT_BUS_SOURCE = "event-bus:daemon"

_LEGACY_DECODE_ERROR = "EventBus cannot decode non-internal event: {event}"
_CONTEXT_TYPE_MISSING = "EventBus envelope payload is missing context_type"
_CONTEXT_TYPE_UNSUPPORTED = "Unsupported EventBus context_type: {context_type}"
_OPERATION_KIND_UNDECLARED = "No earlier outcome representation for operation kind: {operation_kind}"


class CompatibilityEventName(StrEnum):
    """Earlier event names retained by the compatibility wire."""

    SESSION_STARTED = "session_started"
    SESSION_CLOSED = "session_closed"
    SESSION_UPDATED = "session_updated"
    SESSION_STATUS = "session_status"


class CompatibilityContextType(StrEnum):
    """Earlier context type labels retained by the compatibility wire."""

    SESSION_LIFECYCLE = "SessionLifecycleContext"
    SESSION_UPDATED = "SessionUpdatedContext"
    SESSION_STATUS = "SessionStatusContext"
    USER_PROMPT_SUBMIT_ACTIVITY = "UserPromptSubmitActivityEvent"
    TOOL_USE_ACTIVITY = "ToolUseActivityEvent"
    AGENT_STOP_ACTIVITY = "AgentStopActivityEvent"


@dataclass(frozen=True)
class MessageEventContext:
    session_id: str
    text: str = ""


@dataclass(frozen=True)
class SessionLifecycleContext:
    session_id: str


@dataclass(frozen=True)
class AgentReadyContext:
    session_id: str
    compaction_launch_context: CompactionLaunchContext | None = None


@dataclass(frozen=True)
class ProjectsChangedContext:
    trigger: ProjectRefreshTrigger


@dataclass(frozen=True)
class SessionUpdatedContext:
    session_id: str
    updated_fields: Mapping[str, object]


@dataclass(frozen=True)
class SessionStatusContext:
    session_id: str
    status: str
    reason: str
    timestamp: str
    last_activity_at: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


@dataclass(frozen=True)
class AgentAvailabilityContext:
    agent: str
    status: AgentAvailabilityStatus | None = None
    status_until: str | None = None
    reason: str | None = None
    error: str | None = None
    model: str | None = None
    model_status: AgentAvailabilityStatus | None = None
    model_status_until: str | None = None
    model_reason: str | None = None


@dataclass(frozen=True)
class BaseAgentActivityEvent:
    session_id: str
    event_type: AgentHookEventType
    timestamp: str | None = None
    canonical_type: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


@dataclass(frozen=True)
class UserPromptSubmitActivityEvent(BaseAgentActivityEvent):
    pass


@dataclass(frozen=True)
class ToolUseActivityEvent(BaseAgentActivityEvent):
    tool_name: str | None = None
    tool_preview: str | None = None


@dataclass(frozen=True)
class AgentStopActivityEvent(BaseAgentActivityEvent):
    summary: str | None = None
    message: str | None = None


type AgentActivityEvent = UserPromptSubmitActivityEvent | ToolUseActivityEvent | AgentStopActivityEvent


@dataclass(frozen=True)
class SessionEscalatedPayload:
    session_id: str


@dataclass(frozen=True)
class JobStartedPayload:
    job_name: str


@dataclass(frozen=True)
class JobCompletedPayload:
    job_name: str


@dataclass(frozen=True)
class JobFailedPayload:
    job_name: str
    error: str | None = None


@dataclass(frozen=True)
class OperationSucceededContext:
    operation_id: str


@dataclass(frozen=True)
class OperationFailedContext:
    operation_id: str
    error: str


type EventContext = (
    AgentActivityEvent
    | AgentAvailabilityContext
    | AgentEventContext
    | AgentReadyContext
    | DeliveryNoComposerContext
    | ErrorEventContext
    | JobCompletedPayload
    | JobFailedPayload
    | JobStartedPayload
    | MessageEventContext
    | OperationFailedContext
    | OperationSucceededContext
    | ProjectsChangedContext
    | SessionEscalatedPayload
    | SessionLifecycleContext
    | SessionStatusContext
    | SessionUpdatedContext
    | SystemCommandContext
)


class InternalEventCompatIngressData(BaseModel):
    """A retained earlier command carrier that must reach its established owner."""

    event_name: str
    context_type: str
    context: JsonDict
    occurrence_id: str


class _CompatibilityForm(BaseModel):
    """Earlier EventBus fields that ride beside one canonical event during fleet coexistence."""

    event_name: str
    context_type: str
    context: JsonDict


def _context_from_payload(payload: Mapping[str, JsonValue]) -> EventContext:
    raw_context_type = payload.get(_CONTEXT_TYPE_KEY)
    if not isinstance(raw_context_type, str):
        raise ValueError(_CONTEXT_TYPE_MISSING)
    builder = _CONTEXT_BUILDERS.get(raw_context_type)
    if builder is None:
        raise ValueError(_CONTEXT_TYPE_UNSUPPORTED.format(context_type=raw_context_type))
    return builder(payload)


def decode_internal_event_envelope(envelope: InternalEventEnvelope) -> tuple[str, EventContext]:
    """Decode an earlier internal envelope without coupling wire translation to EventBus."""
    if not envelope.event.startswith(INTERNAL_EVENT_NAMESPACE_PREFIX):
        raise ValueError(_LEGACY_DECODE_ERROR.format(event=envelope.event))
    return envelope.event.removeprefix(INTERNAL_EVENT_NAMESPACE_PREFIX), _context_from_payload(envelope.payload)


def wire_internal_event_name(event_name: str) -> str:
    """Encode the earlier internal event namespace used by supported peers."""
    return INTERNAL_EVENT_NAMESPACE_PREFIX + event_name


def legacy_internal_event_codec() -> EntryCodec[InternalEventEnvelope]:
    """Codec for an earlier daemon reader during staged migration only."""
    return EntryCodec(
        decode=lambda entry, entry_id: InternalEventEnvelope.from_stream_dict(entry, entry_id=entry_id),
        event_id=lambda envelope: envelope.idempotency_key or envelope.event_id,
    )


def decode_compat_ingress_context(data: InternalEventCompatIngressData) -> EventContext:
    """Decode a retained command/event carrier after its consumer has checked source ownership."""
    context = _context_from_payload(data.context)
    if type(context).__name__ != data.context_type:
        raise ValueError("Internal compatibility context type does not match its payload")
    return context


def encode_legacy_context(context: EventContext) -> JsonDict:
    """Encode an earlier typed EventBus context for peers that still consume its wire."""
    if not dataclasses.is_dataclass(context) or isinstance(context, type):
        raise TypeError(f"Expected dataclass for EventBus context, got {type(context).__name__}")
    payload = _json_object(context)
    payload[_CONTEXT_TYPE_KEY] = type(context).__name__
    return payload


def _json_object(value: object) -> JsonDict:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise TypeError(f"Expected dataclass or mapping for EventBus payload, got {type(value).__name__}")


def _json_value(value: object) -> JsonValue:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_object(value)
    if isinstance(value, Mapping):
        return _json_object(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.replace(tzinfo=UTC).isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    raise TypeError(f"Unsupported EventBus payload value: {type(value).__name__}")


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
        runtime_run_id=_optional_str(payload.get("runtime_run_id")),
        compaction_launch_context=decode_compaction_launch_context(payload.get(COMPACTION_LAUNCH_CONTEXT_FIELD)),
    )


def _build_agent_ready_context(payload: Mapping[str, JsonValue]) -> AgentReadyContext:
    return AgentReadyContext(
        session_id=_required_str(payload, "session_id"),
        compaction_launch_context=decode_compaction_launch_context(payload.get(COMPACTION_LAUNCH_CONTEXT_FIELD)),
    )


def _build_projects_changed_context(payload: Mapping[str, JsonValue]) -> ProjectsChangedContext:
    return ProjectsChangedContext(trigger=ProjectRefreshTrigger(_required_str(payload, "trigger")))


def _build_availability_context(payload: Mapping[str, JsonValue]) -> EventContext:
    status = _optional_str(payload.get("status"))
    model_status = _optional_str(payload.get("model_status"))
    return AgentAvailabilityContext(
        agent=_required_str(payload, "agent"),
        status=AgentAvailabilityStatus(status) if status is not None else None,
        status_until=_optional_str(payload.get("status_until")),
        reason=_optional_str(payload.get("reason")),
        error=_optional_str(payload.get("error")),
        model=_optional_str(payload.get("model")),
        model_status=AgentAvailabilityStatus(model_status) if model_status is not None else None,
        model_status_until=_optional_str(payload.get("model_status_until")),
        model_reason=_optional_str(payload.get("model_reason")),
    )


def _build_system_command_context(payload: Mapping[str, JsonValue]) -> EventContext:
    raw_payload = payload.get("payload")
    return SystemCommandContext(
        command=_optional_str(payload.get("command")) or "",
        from_computer=_optional_str(payload.get("from_computer")) or "unknown",
        payload=SessionOutputStoppedPayload.from_dict(raw_payload),
    )


def _agent_event_payload(event_type: AgentHookEventType, payload: Mapping[str, JsonValue]) -> AgentEventPayload:
    source = payload.get("raw")
    raw = dict(source) if isinstance(source, Mapping) else {}
    for key in (
        "session_id",
        "transcript_path",
        "prompt",
        "source_computer",
        "tool_call_id",
        "tool_batch_resolved",
        "agent_status_reason",
        "reason",
        "notification_type",
        "error",
        "terminationReason",
        "agent_name",
        "native_event_type",
        "native_event_details",
        "received_at",
        "receiver_ingress_id",
    ):
        if key in payload:
            raw[key] = payload[key]
    return build_agent_payload(event_type, raw)


def _agent_hook_event_type(value: JsonValue | None) -> AgentHookEventType:
    if not isinstance(value, str):
        raise ValueError(f"Unsupported agent hook event_type: {value!r}")
    if value not in ALL_AGENT_HOOK_EVENTS:
        raise ValueError(f"Unsupported agent hook event_type: {value!r}")
    return AgentHookEvents(value)


def _required_mapping(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    return _mapping_value(payload.get(key), field_name=key)


def _mapping_value(value: JsonValue | None, *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected mapping for {field_name}")
    return cast(Mapping[str, JsonValue], value)


def _required_str(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Expected string for {key}")
    return value


def _optional_str(value: JsonValue | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Expected optional string, got {value!r}")
    return value


_CONTEXT_BUILDERS: Mapping[str, Callable[[Mapping[str, JsonValue]], EventContext]] = {
    "AgentAvailabilityContext": _build_availability_context,
    "AgentEventContext": _build_agent_event_context,
    "AgentReadyContext": _build_agent_ready_context,
    CompatibilityContextType.AGENT_STOP_ACTIVITY: lambda payload: _build_dataclass_context(
        AgentStopActivityEvent, payload
    ),
    "DeliveryNoComposerContext": lambda payload: _build_dataclass_context(DeliveryNoComposerContext, payload),
    "ErrorEventContext": lambda payload: _build_dataclass_context(ErrorEventContext, payload),
    "JobCompletedPayload": lambda payload: _build_dataclass_context(JobCompletedPayload, payload),
    "JobFailedPayload": lambda payload: _build_dataclass_context(JobFailedPayload, payload),
    "JobStartedPayload": lambda payload: _build_dataclass_context(JobStartedPayload, payload),
    "MessageEventContext": lambda payload: _build_dataclass_context(MessageEventContext, payload),
    "OperationFailedContext": lambda payload: _build_dataclass_context(OperationFailedContext, payload),
    "OperationSucceededContext": lambda payload: _build_dataclass_context(OperationSucceededContext, payload),
    "ProjectsChangedContext": _build_projects_changed_context,
    "SessionEscalatedPayload": lambda payload: _build_dataclass_context(SessionEscalatedPayload, payload),
    CompatibilityContextType.SESSION_LIFECYCLE: lambda payload: _build_dataclass_context(
        SessionLifecycleContext, payload
    ),
    CompatibilityContextType.SESSION_STATUS: lambda payload: _build_dataclass_context(SessionStatusContext, payload),
    CompatibilityContextType.SESSION_UPDATED: lambda payload: _build_dataclass_context(SessionUpdatedContext, payload),
    "SystemCommandContext": _build_system_command_context,
    CompatibilityContextType.TOOL_USE_ACTIVITY: lambda payload: _build_dataclass_context(ToolUseActivityEvent, payload),
    CompatibilityContextType.USER_PROMPT_SUBMIT_ACTIVITY: lambda payload: _build_dataclass_context(
        UserPromptSubmitActivityEvent, payload
    ),
}


def compatibility_form(event: ReceivedEvent) -> _CompatibilityForm:
    """Translate one native runtime fact to the precise earlier EventBus context it replaced."""
    data = event.data
    if event.type == RuntimeSessionSourceChanged.NAME:
        source = RuntimeSessionSourceChangedData.model_validate(data)
        if source.change is RuntimeSessionChange.CREATED:
            return _CompatibilityForm(
                event_name=CompatibilityEventName.SESSION_STARTED,
                context_type=CompatibilityContextType.SESSION_LIFECYCLE,
                context={"session_id": source.session_id},
            )
        if source.change is RuntimeSessionChange.CLOSED:
            return _CompatibilityForm(
                event_name=CompatibilityEventName.SESSION_CLOSED,
                context_type=CompatibilityContextType.SESSION_LIFECYCLE,
                context={"session_id": source.session_id},
            )
        return _CompatibilityForm(
            event_name=CompatibilityEventName.SESSION_UPDATED,
            context_type=CompatibilityContextType.SESSION_UPDATED,
            context={
                "session_id": source.session_id,
                "updated_fields": dict.fromkeys(source.changed_fields),
            },
        )
    if event.type == RuntimeSessionStatusChanged.NAME:
        status = RuntimeSessionStatusData.model_validate(data)
        return _CompatibilityForm(
            event_name=CompatibilityEventName.SESSION_STATUS,
            context_type=CompatibilityContextType.SESSION_STATUS,
            context=status.model_dump(mode="json"),
        )
    if event.type == RuntimeAgentActivityObserved.NAME:
        activity = RuntimeAgentActivityData.model_validate(data)
        details = activity.details
        if activity.event_type is AgentHookEvents.USER_PROMPT_SUBMIT:
            context_type = CompatibilityContextType.USER_PROMPT_SUBMIT_ACTIVITY
            context = _activity_context(activity)
        elif activity.event_type is AgentHookEvents.PRE_TOOL_USE:
            context_type = CompatibilityContextType.TOOL_USE_ACTIVITY
            context = {
                **_activity_context(activity),
                "tool_name": details.get("tool_name"),
                "tool_preview": details.get("tool_preview"),
            }
        elif activity.event_type is AgentHookEvents.AGENT_STOP:
            context_type = CompatibilityContextType.AGENT_STOP_ACTIVITY
            context = {
                **_activity_context(activity),
                "summary": details.get("summary"),
                "message": details.get("message"),
            }
        else:
            raise ValueError(f"Unsupported runtime activity type: {activity.event_type}")
        return _CompatibilityForm(
            event_name="agent_activity",
            context_type=context_type,
            context=dict(context),
        )
    if event.type == "teleclaude.agent_runtime.agent.availability_changed":
        availability = RuntimeAgentAvailabilityData.model_validate(data)
        return _CompatibilityForm(
            event_name="agent_availability",
            context_type="AgentAvailabilityContext",
            context=availability.model_dump(mode="json"),
        )
    if event.type == "teleclaude.agent_runtime.error.reported":
        error = RuntimeErrorData.model_validate(data)
        return _CompatibilityForm(
            event_name="error",
            context_type="ErrorEventContext",
            context=error.model_dump(mode="json"),
        )
    if event.type in {RuntimeOperationSucceeded.type_name(), RuntimeOperationFailed.type_name()}:
        outcome = RuntimeOperationOutcomeData.model_validate(data)
        succeeded = event.type == RuntimeOperationSucceeded.type_name()
        event_pair = outcome_events_for(outcome.operation_kind)
        if event_pair is None:
            raise ValueError(_OPERATION_KIND_UNDECLARED.format(operation_kind=outcome.operation_kind))
        return _CompatibilityForm(
            event_name=event_pair[0] if succeeded else event_pair[1],
            context_type="OperationSucceededContext" if succeeded else "OperationFailedContext",
            context={
                "operation_id": outcome.operation_id,
                **({"error": outcome.error or ""} if not succeeded else {}),
            },
        )
    raise ValueError(f"No earlier internal representation for {event.type}")


def _activity_context(data: RuntimeAgentActivityData) -> JsonDict:
    return {
        "session_id": data.session_id,
        "event_type": data.event_type,
        "timestamp": data.timestamp,
        "canonical_type": data.canonical_type,
        "message_intent": data.message_intent,
        "delivery_scope": data.delivery_scope,
    }


def encode_internal_compatibility(
    event: ReceivedEvent,
    entry: dict[str, str],
    legacy: LegacyFacts,
) -> dict[str, str]:
    """Add the earlier EventBus fields beside the canonical source attributes in one append."""
    form = compatibility_form(event)
    entry["ce_data"] = entry["payload"]
    entry.update(
        {
            "event": INTERNAL_EVENT_NAMESPACE_PREFIX + form.event_name,
            "event_id": event.id,
            "version": str(INTERNAL_STREAM_VERSION),
            "source": _EVENT_BUS_SOURCE,
            "originating_computer": event.source,
            "originating_session_id": _EMPTY,
            "origin_home": _EMPTY,
            "subject": _NO_HOME,
            "subject_owner": _NO_HOME,
            "timestamp": event.time.isoformat(),
            "idempotency_key": event.id,
            "level": str(int(legacy.level)),
            "domain": "internal",
            "entity": _EMPTY,
            "description": _EMPTY,
            "visibility": legacy.visibility.value,
            "payload": json.dumps({**form.context, _CONTEXT_TYPE_KEY: form.context_type}),
            "actions": _EMPTY,
            "human_action": _EMPTY,
            "terminal_when": _EMPTY,
            "resolution_shape": _EMPTY,
        }
    )
    return entry


def decode_internal_event_entry(entry: object, entry_id: str) -> StreamEvent:
    """Decode a dual-written native entry or upcast a retained earlier EventBus entry once."""
    if not isinstance(entry, dict):
        raise ValueError("internal stream entry must be a mapping")
    if not entry:
        raise RuntimeError(f"internal_event_retention_limit: pending stream entry {entry_id} has no retained payload")
    text_entry = {_text(key): _text(value) for key, value in cast(Mapping[object, object], entry).items()}
    if "ce_type" in text_entry:
        canonical_entry = dict(text_entry)
        if "ce_data" in canonical_entry:
            canonical_entry["payload"] = canonical_entry["ce_data"]
        return decode_platform_event(canonical_entry, entry_id)
    if not text_entry.get("event", "").startswith(INTERNAL_EVENT_NAMESPACE_PREFIX):
        return decode_platform_event(text_entry, entry_id)

    envelope = InternalEventEnvelope.from_stream_dict(text_entry, entry_id=entry_id)
    name, context = decode_internal_event_envelope(envelope)
    translated = _upcast_legacy_event(name, context, envelope.originating_computer)
    if translated is not None:
        event_type, subject, data = translated
    else:
        payload = dict(envelope.payload)
        ingress = InternalEventCompatIngressData(
            event_name=name,
            context_type=str(payload.get(_CONTEXT_TYPE_KEY) or type(context).__name__),
            context=payload,
            occurrence_id=envelope.idempotency_key or envelope.event_id,
        )
        event_type = INTERNAL_COMPAT_INGRESS_TYPE
        subject = _subject_for_legacy_context(context, envelope.originating_computer)
        data = ingress.model_dump(mode="json")
    occurrence = envelope.idempotency_key or envelope.event_id or occurrence_id(INTERNAL_EVENT_STREAM, entry_id)
    return StreamEvent(
        id=occurrence,
        type=event_type,
        source=envelope.originating_computer or "",
        subject=subject,
        time=envelope.timestamp,
        data=data,
        home=EventHomeMarker.UNKNOWN,
        home_owner=EventHomeOwnerMarker.NONE,
        legacy=_legacy_facts(text_entry, envelope),
    )


def internal_event_entry_codec() -> EntryCodec[StreamEvent]:
    """The internal stream's canonical-first compatibility decoder."""
    return EntryCodec(decode=decode_internal_event_entry, event_id=lambda event: event.id)


def _legacy_facts(entry: Mapping[str, str], envelope: InternalEventEnvelope) -> LegacyFacts:
    level = entry.get("level", str(int(EventLevel.WORKFLOW)))
    return LegacyFacts(
        producer=envelope.source,
        level=EventLevel(int(level)),
        domain=entry.get("domain", "internal"),
        entity=entry.get("entity") or None,
        description=entry.get("description", ""),
        visibility=envelope.visibility,
        idempotency_key=envelope.idempotency_key,
    )


def _upcast_legacy_event(
    event_name: str,
    context: EventContext,
    originating_computer: str | None,
) -> tuple[str, EventRef | None, JsonDict] | None:
    if event_name == CompatibilityEventName.SESSION_STARTED and isinstance(context, SessionLifecycleContext):
        source_data = RuntimeSessionSourceChangedData(
            session_id=context.session_id, change=RuntimeSessionChange.CREATED
        )
        return (
            RuntimeSessionSourceChanged.NAME,
            SessionRef(context.session_id).to_ref(),
            source_data.model_dump(mode="json"),
        )
    if event_name == CompatibilityEventName.SESSION_CLOSED and isinstance(context, SessionLifecycleContext):
        source_data = RuntimeSessionSourceChangedData(session_id=context.session_id, change=RuntimeSessionChange.CLOSED)
        return (
            RuntimeSessionSourceChanged.NAME,
            SessionRef(context.session_id).to_ref(),
            source_data.model_dump(mode="json"),
        )
    if event_name == CompatibilityEventName.SESSION_UPDATED and isinstance(context, SessionUpdatedContext):
        source_data = RuntimeSessionSourceChangedData(
            session_id=context.session_id,
            change=RuntimeSessionChange.UPDATED,
            changed_fields=list(context.updated_fields),
        )
        return (
            RuntimeSessionSourceChanged.NAME,
            SessionRef(context.session_id).to_ref(),
            source_data.model_dump(mode="json"),
        )
    if event_name == CompatibilityEventName.SESSION_STATUS and isinstance(context, SessionStatusContext):
        status_data = RuntimeSessionStatusData(
            session_id=context.session_id,
            status=context.status,
            reason=context.reason,
            timestamp=context.timestamp,
            last_activity_at=context.last_activity_at,
            message_intent=context.message_intent,
            delivery_scope=context.delivery_scope,
        )
        return (
            RuntimeSessionStatusChanged.NAME,
            SessionRef(context.session_id).to_ref(),
            status_data.model_dump(mode="json"),
        )
    if event_name == "agent_activity" and isinstance(
        context, AgentStopActivityEvent | ToolUseActivityEvent | UserPromptSubmitActivityEvent
    ):
        event_type = context.event_type
        details: JsonDict = {}
        if isinstance(context, ToolUseActivityEvent):
            details.update({"tool_name": context.tool_name, "tool_preview": context.tool_preview})
        elif isinstance(context, AgentStopActivityEvent):
            details.update({"summary": context.summary, "message": context.message})
        activity_data = RuntimeAgentActivityData(
            session_id=context.session_id,
            event_type=event_type,
            timestamp=context.timestamp,
            canonical_type=context.canonical_type,
            message_intent=context.message_intent,
            delivery_scope=context.delivery_scope,
            details=details,
        )
        return (
            "teleclaude.agent_runtime.agent.activity_observed",
            SessionRef(context.session_id).to_ref(),
            activity_data.model_dump(mode="json"),
        )
    if event_name == "agent_availability" and isinstance(context, AgentAvailabilityContext):
        availability_data = RuntimeAgentAvailabilityData(
            agent=context.agent,
            status=context.status,
            status_until=context.status_until,
            reason=context.reason,
            error=context.error,
            model=context.model,
            model_status=context.model_status,
            model_status_until=context.model_status_until,
            model_reason=context.model_reason,
        )
        subject = ComputerRef(originating_computer).to_ref() if originating_computer else None
        return (
            "teleclaude.agent_runtime.agent.availability_changed",
            subject,
            availability_data.model_dump(mode="json"),
        )
    if event_name == "error" and isinstance(context, ErrorEventContext):
        error_data = RuntimeErrorData(
            session_id=context.session_id,
            message=context.message,
            source=context.source,
            details=cast(JsonDict, dict(context.details)) if context.details is not None else None,
            severity=context.severity,
            retryable=context.retryable,
            code=context.code,
        )
        subject = SessionRef(context.session_id).to_ref() if context.session_id else None
        return "teleclaude.agent_runtime.error.reported", subject, error_data.model_dump(mode="json")
    operation_outcome = kind_for_outcome_event(event_name)
    if operation_outcome is not None and isinstance(context, OperationSucceededContext | OperationFailedContext):
        kind, succeeded = operation_outcome
        outcome_data = RuntimeOperationOutcomeData(
            operation_id=context.operation_id,
            operation_kind=kind.value,
            error=context.error if isinstance(context, OperationFailedContext) else None,
        )
        return (
            RuntimeOperationSucceeded.type_name() if succeeded else RuntimeOperationFailed.type_name(),
            OperationRef(context.operation_id).to_ref(),
            outcome_data.model_dump(mode="json"),
        )
    return None


def _subject_for_legacy_context(context: EventContext, computer: str | None) -> EventRef | None:
    if isinstance(context, (SessionLifecycleContext, SessionUpdatedContext, SessionStatusContext)):
        return SessionRef(context.session_id).to_ref()
    if isinstance(context, (AgentStopActivityEvent, ToolUseActivityEvent, UserPromptSubmitActivityEvent)):
        return SessionRef(context.session_id).to_ref()
    if isinstance(context, AgentEventContext):
        return SessionRef(context.session_id).to_ref()
    if isinstance(context, OperationFailedContext | OperationSucceededContext):
        return OperationRef(context.operation_id).to_ref()
    if isinstance(context, AgentAvailabilityContext) and computer:
        return ComputerRef(computer).to_ref()
    return None


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
