"""Event emission REST endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from teleclaude.api.auth import CLEARANCE_EVENTS_EMIT, CallerIdentity
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.producer import emit_event

router = APIRouter(tags=["events"])


class EmitEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_id: str


@router.post("/events/emit", response_model=EmitEventResponse)
async def emit_event_endpoint(
    body: EventEnvelope,
    _identity: CallerIdentity = Depends(CLEARANCE_EVENTS_EMIT),
) -> EmitEventResponse:
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
