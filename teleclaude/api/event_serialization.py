"""Serialization helpers for live API events."""

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    AgentAvailabilityEventDTO,
    ModelAvailabilityDeltaDTO,
)
from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.agents import is_agent_enabled
from teleclaude.core.events import AgentAvailabilityContext


def availability_legacy_fields(
    status: AgentAvailabilityStatus | None,
    status_until: str | None,
) -> tuple[bool | None, str | None, str | None]:
    """Derive retained fleet-compatible fields from the typed status once."""
    if status is None:
        return None, None, None
    return (
        status is not AgentAvailabilityStatus.UNAVAILABLE,
        status_until if status is AgentAvailabilityStatus.UNAVAILABLE else None,
        status_until if status is AgentAvailabilityStatus.DEGRADED else None,
    )


def build_model_availability_delta(
    model: str | None,
    status: AgentAvailabilityStatus | None,
    status_until: str | None,
    reason: str | None,
) -> ModelAvailabilityDeltaDTO | None:
    """Build the optional live delta carried by an availability event."""
    if model is None or status is None:
        return None
    return ModelAvailabilityDeltaDTO(
        model=model,
        status=status,
        status_until=status_until,
        active=status is not AgentAvailabilityStatus.AVAILABLE,
        unavailable_until=availability_legacy_fields(status, status_until)[1],
        reason=reason,
    )


def agent_availability_event_dto(context: AgentAvailabilityContext) -> AgentAvailabilityEventDTO:
    """Convert an availability event context to its WebSocket DTO."""
    available, unavailable_until, degraded_until = availability_legacy_fields(context.status, context.status_until)
    return AgentAvailabilityEventDTO(
        data=AgentAvailabilityDTO(
            agent=context.agent,
            available=available,
            enabled=is_agent_enabled(context.agent),
            status=context.status,
            status_until=context.status_until,
            unavailable_until=unavailable_until,
            degraded_until=degraded_until,
            reason=context.reason,
            error=context.error,
            model_delta=build_model_availability_delta(
                context.model,
                context.model_status,
                context.model_status_until,
                context.model_reason,
            ),
        )
    )
