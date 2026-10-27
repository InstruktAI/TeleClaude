"""Independent reactions to typed agent-runtime facts on the internal stream."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, cast

from pydantic import BaseModel

from teleclaude.config.machine import config
from teleclaude.core.events import AgentHookEventType, ErrorEventContext, ErrorSeverity
from teleclaude.core.models._session import SessionField
from teleclaude.events.consumers import Consumer, ConsumerDelivery, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.references import ReferenceKind
from teleclaude.events.schemas.system import (
    RuntimeAgentActivityData,
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
from teleclaude.events.type_pattern import TypePattern
from teleclaude.transport.internal_event_compat import (
    INTERNAL_COMPAT_INGRESS_TYPE,
    InternalEventCompatIngressData,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.lifecycle import DaemonLifecycle

_SOURCE_CHANGED = RuntimeSessionSourceChanged.NAME
_STATUS_CHANGED = RuntimeSessionStatusChanged.NAME
_ACTIVITY_OBSERVED = "teleclaude.agent_runtime.agent.activity_observed"
_AVAILABILITY_CHANGED = "teleclaude.agent_runtime.agent.availability_changed"
_ERROR_REPORTED = "teleclaude.agent_runtime.error.reported"

_SESSION_SOURCE_INTEREST = Interest(
    types=(TypePattern(_SOURCE_CHANGED),),
    own_computer_only=True,
    subject_kinds=frozenset({ReferenceKind.SESSION}),
)
_SESSION_UPDATE_ROUTING_INTEREST = Interest(
    types=(TypePattern(_SOURCE_CHANGED),),
    subject_kinds=frozenset({ReferenceKind.SESSION}),
)
_CONVERSATION_INTEREST = Interest(
    types=(TypePattern(_ACTIVITY_OBSERVED),),
    own_computer_only=True,
    subject_kinds=frozenset({ReferenceKind.SESSION}),
)
_ERROR_INTEREST = Interest(types=(TypePattern(_ERROR_REPORTED),))
_AVAILABILITY_INTEREST = Interest(
    types=(TypePattern(_AVAILABILITY_CHANGED),),
    subject_kinds=frozenset({ReferenceKind.COMPUTER}),
)
_OPERATION_INTEREST = Interest(
    types=(TypePattern(RuntimeOperationSucceeded.type_name()), TypePattern(RuntimeOperationFailed.type_name())),
    subject_kinds=frozenset({ReferenceKind.OPERATION}),
)

_MATERIALIZER_CONSUMER = "runtime-session-materializer"
_FINAL_CLOSE_CONSUMER = "runtime-final-close-housekeeping"
_ADAPTER_STATUS_CONSUMER = "runtime-adapter-session-status"
_ADAPTER_UPDATE_CONSUMER = "runtime-adapter-session-update"
_API_STATUS_CONSUMER = "runtime-api-session-status"
_API_ACTIVITY_CONSUMER = "runtime-api-agent-activity"
_API_AVAILABILITY_CONSUMER = "runtime-api-agent-availability"
_API_ERROR_CONSUMER = "runtime-api-error"
_API_OPERATION_CONSUMER = "runtime-api-operation-outcome"
_DISCORD_VOICE_CONSUMER = "runtime-discord-voice-status"
_DAEMON_ERROR_FEEDBACK_CONSUMER = "runtime-daemon-error-feedback"
_COMPAT_INGRESS_CONSUMER = "runtime-internal-compat-ingress"
_CONVERSATION_CONSUMER = "runtime-github-conversation-capture"
_CURRENT_REQUEST_SURFACE_REQUIRED = "runtime event reaction requires the lifecycle's current API server"


class RuntimeApiSurface(Protocol):
    """The lifecycle-owned request surface used by live presentation reactions."""

    async def handle_runtime_session_status(self, data: RuntimeSessionStatusData) -> None: ...

    async def handle_runtime_agent_activity(self, data: RuntimeAgentActivityData) -> None: ...

    async def handle_runtime_agent_availability(self, data: RuntimeAgentAvailabilityData) -> None: ...

    async def handle_runtime_error(self, data: RuntimeErrorData) -> None: ...

    async def handle_runtime_operation_outcome(self, data: RuntimeOperationOutcomeData, *, succeeded: bool) -> None: ...

    async def recover_runtime_availability(self) -> None: ...


class RuntimeVoiceSurface(Protocol):
    """Discord's current-source voice-focus recovery capability."""

    async def recover_runtime_voice_focus(self) -> None: ...

    async def handle_runtime_session_status(self, context: RuntimeSessionStatusData) -> None: ...


def _typed_data[DataT: BaseModel](event: ReceivedEvent, model: type[DataT]) -> DataT:
    return model.model_validate(event.data)


def _current_api(lifecycle: DaemonLifecycle) -> RuntimeApiSurface:
    api_server = lifecycle.api_server
    if api_server is None:
        raise RuntimeError(_CURRENT_REQUEST_SURFACE_REQUIRED)
    return cast(RuntimeApiSurface, api_server)


def _conversation_consumer(
    capture: Callable[[str], Awaitable[None]], recover: Callable[[], Awaitable[None]]
) -> Consumer:
    """The reaction that captures a session's conversation turns when its agent stops.

    The stop event carries no content and its loss loses nothing: every pass takes every completed turn after the
    last one captured, and the recovery operation runs that pass over every eligible session this computer hosts.
    Events are not coalesced: a later activity of the same session must not stand in for its stop.
    """

    async def react(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeAgentActivityData)
        if data.event_type == AgentHookEventType.AGENT_STOP:
            await capture(data.session_id)

    return Consumer(
        _CONVERSATION_CONSUMER,
        _CONVERSATION_INTEREST,
        react,
        delivery=ConsumerDelivery.LIVE,
        recover=recover,
    )


def build_runtime_event_consumers(
    *,
    lifecycle: DaemonLifecycle,
    client: AdapterClient,
    close_housekeeping: Callable[[str], Awaitable[None]],
    recover_housekeeping: Callable[[], Awaitable[None]],
    report_error: Callable[[ErrorEventContext], Awaitable[object]],
    discord_voice_status: Callable[[RuntimeSessionStatusData], Awaitable[None]],
    recover_discord_voice: Callable[[], Awaitable[None]],
    compatibility_ingress: Callable[[InternalEventCompatIngressData, ReceivedEvent], Awaitable[None]],
    capture_conversation: Callable[[str], Awaitable[None]],
    recover_conversation: Callable[[], Awaitable[None]],
) -> list[Consumer]:
    """Build independent internal-stream reactions while resolving replaceable surfaces at delivery time."""

    async def materialize_session(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeSessionSourceChangedData)
        await lifecycle.session_materializer.reconcile(data.session_id)

    async def close_final_session(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeSessionSourceChangedData)
        if data.change is RuntimeSessionChange.CLOSED:
            await close_housekeeping(data.session_id)

    async def route_session_status(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeSessionStatusData)
        await client.dispatch_session_status(data.session_id, data.status)

    async def route_session_update(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeSessionSourceChangedData)
        if data.change is RuntimeSessionChange.UPDATED and data.changed_fields:
            await client.dispatch_session_update(data.session_id, dict.fromkeys(data.changed_fields))

    async def recover_session_updates() -> None:
        sessions = await lifecycle.session_materializer.source_sessions()
        for session in sessions:
            await client.dispatch_session_update(
                session.session_id, dict.fromkeys(field.value for field in SessionField), ensure_channels=False
            )

    async def recover_availability() -> None:
        await _current_api(lifecycle).recover_runtime_availability()

    async def api_session_status(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeSessionStatusData)
        await _current_api(lifecycle).handle_runtime_session_status(data)

    async def api_activity(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeAgentActivityData)
        await _current_api(lifecycle).handle_runtime_agent_activity(data)

    async def api_availability(event: ReceivedEvent) -> None:
        await recover_availability()

    async def api_error(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeErrorData)
        await _current_api(lifecycle).handle_runtime_error(data)

    async def daemon_error(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeErrorData)
        await report_error(
            ErrorEventContext(
                session_id=data.session_id,
                message=data.message,
                source=data.source,
                details=data.details,
                severity=cast(ErrorSeverity, data.severity),
                retryable=data.retryable,
                code=data.code,
            )
        )

    async def api_operation_outcome(event: ReceivedEvent) -> None:
        data = _typed_data(event, RuntimeOperationOutcomeData)
        await _current_api(lifecycle).handle_runtime_operation_outcome(
            data,
            succeeded=event.type == RuntimeOperationSucceeded.type_name(),
        )

    async def route_compatibility_ingress(event: ReceivedEvent) -> None:
        data = _typed_data(event, InternalEventCompatIngressData)
        await compatibility_ingress(data, event)

    async def route_discord_voice_status(event: ReceivedEvent) -> None:
        await discord_voice_status(_typed_data(event, RuntimeSessionStatusData))

    async def recover_voice_focus() -> None:
        await lifecycle.session_materializer.reconcile_current()
        await recover_discord_voice()

    consumers = [
        Consumer(
            _MATERIALIZER_CONSUMER,
            _SESSION_SOURCE_INTEREST,
            materialize_session,
            delivery=ConsumerDelivery.LIVE,
            recover=lifecycle.session_materializer.reconcile_current,
            coalesce=True,
        ),
        Consumer(
            _FINAL_CLOSE_CONSUMER,
            _SESSION_SOURCE_INTEREST,
            close_final_session,
            delivery=ConsumerDelivery.LIVE,
            recover=recover_housekeeping,
        ),
        Consumer(
            _ADAPTER_STATUS_CONSUMER,
            Interest(types=(TypePattern(_STATUS_CHANGED),)),
            route_session_status,
            delivery=ConsumerDelivery.LIVE,
        ),
        Consumer(
            _ADAPTER_UPDATE_CONSUMER,
            _SESSION_UPDATE_ROUTING_INTEREST,
            route_session_update,
            delivery=ConsumerDelivery.LIVE,
            recover=recover_session_updates,
        ),
        Consumer(
            _API_STATUS_CONSUMER,
            Interest(types=(TypePattern(_STATUS_CHANGED),)),
            api_session_status,
            delivery=ConsumerDelivery.LIVE,
        ),
        Consumer(
            _API_ACTIVITY_CONSUMER,
            Interest(types=(TypePattern(_ACTIVITY_OBSERVED),)),
            api_activity,
            delivery=ConsumerDelivery.LIVE,
        ),
        Consumer(
            _API_AVAILABILITY_CONSUMER,
            _AVAILABILITY_INTEREST,
            api_availability,
            delivery=ConsumerDelivery.LIVE,
            recover=recover_availability,
            coalesce=True,
        ),
        _conversation_consumer(capture_conversation, recover_conversation),
        Consumer(_API_ERROR_CONSUMER, _ERROR_INTEREST, api_error, delivery=ConsumerDelivery.LIVE),
        Consumer(_DAEMON_ERROR_FEEDBACK_CONSUMER, _ERROR_INTEREST, daemon_error, delivery=ConsumerDelivery.LIVE),
        Consumer(_API_OPERATION_CONSUMER, _OPERATION_INTEREST, api_operation_outcome, delivery=ConsumerDelivery.LIVE),
        Consumer(
            _COMPAT_INGRESS_CONSUMER,
            Interest(types=(TypePattern(INTERNAL_COMPAT_INGRESS_TYPE),)),
            route_compatibility_ingress,
        ),
    ]
    if config.discord.token:
        consumers.append(
            Consumer(
                _DISCORD_VOICE_CONSUMER,
                Interest(types=(TypePattern(_STATUS_CHANGED),)),
                route_discord_voice_status,
                delivery=ConsumerDelivery.LIVE,
                recover=recover_voice_focus,
            )
        )
    return consumers
