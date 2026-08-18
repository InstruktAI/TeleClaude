"""Serialization helpers for live API events."""

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    AgentAvailabilityEventDTO,
    build_model_availability_delta,
)
from teleclaude.core.events import AgentAvailabilityContext


def agent_availability_event_dto(context: AgentAvailabilityContext) -> AgentAvailabilityEventDTO:
    """Convert an availability event context to its WebSocket DTO."""
    return AgentAvailabilityEventDTO(
        data=AgentAvailabilityDTO(
            agent=context.agent,
            available=context.available,
            status=context.status,
            unavailable_until=context.unavailable_until,
            degraded_until=context.degraded_until,
            reason=context.reason,
            error=context.error,
            model_delta=build_model_availability_delta(
                context.model,
                context.model_active,
                context.model_unavailable_until,
                context.model_reason,
            ),
        )
    )
