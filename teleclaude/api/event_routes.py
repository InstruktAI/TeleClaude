"""Event emission REST endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import CallerIdentity, clearance_events_emit
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.producer import emit_event

router = APIRouter(tags=["events"])


class EmitEventResponse(BaseModel):
    """Response payload for successful event emission."""

    model_config = ConfigDict(frozen=True)

    entry_id: str


@router.post("/events/emit", response_model=EmitEventResponse)
async def emit_event_endpoint(
    body: EventEnvelope,
    _identity: CallerIdentity = Depends(clearance_events_emit),
) -> EmitEventResponse:
    """Emit an event envelope and return the durable entry id."""
    entry_id = await emit_event(
        event=body.event,
        source=body.source,
        level=body.level,
        domain=body.domain,
        description=body.description,
        payload=body.payload,
        visibility=body.visibility,
        entity=body.entity,
    )
    return EmitEventResponse(entry_id=entry_id)
