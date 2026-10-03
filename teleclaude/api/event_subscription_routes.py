"""Authenticated caller-session event subscription API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import (
    EventSubscriptionDTO,
    EventSubscriptionMutationResponseDTO,
    EventSubscriptionRequest,
)
from teleclaude.core.db import db
from teleclaude.core.event_subscription_mode import EventSubscriptionMode
from teleclaude.core.session_status import is_session_terminal

if TYPE_CHECKING:
    from teleclaude.core.event_subscriptions import EventSubscriptionService
    from teleclaude.core.models import Session

router = APIRouter(prefix="/event-subscriptions", tags=["event subscriptions"])

_event_subscription_service: EventSubscriptionService | None = None
_SERVICE_UNAVAILABLE = "event subscription service is not configured"
_SESSION_REQUIRED = "event subscriptions require an authenticated caller session"
_SESSION_NOT_AVAILABLE = "the caller session is not available"


def configure(service: EventSubscriptionService | None) -> None:
    """Wire the daemon-owned event subscription service."""
    global _event_subscription_service
    _event_subscription_service = service


def _service() -> EventSubscriptionService:
    service = _event_subscription_service
    if service is None:
        raise HTTPException(status_code=503, detail=_SERVICE_UNAVAILABLE)
    return service


def _session_id(identity: CallerIdentity) -> str:
    if not identity.session_id:
        raise HTTPException(status_code=403, detail=_SESSION_REQUIRED)
    return identity.session_id


async def _live_session(session_id: str) -> Session:
    session = await db.get_session(session_id)
    if session is None or is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise HTTPException(status_code=404, detail=_SESSION_NOT_AVAILABLE)
    return session


def _subscription_dto(
    subscription_id: str,
    event_type: str,
    mode: str,
    narrowing_json: str,
    created_at: str,
) -> EventSubscriptionDTO:
    return EventSubscriptionDTO(
        id=subscription_id,
        event_type=event_type,
        mode=EventSubscriptionMode(mode),
        narrowing=json.loads(narrowing_json),
        created_at=created_at,
    )


@router.post("", response_model=EventSubscriptionDTO)
async def subscribe(
    request: EventSubscriptionRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> EventSubscriptionDTO:
    """Create one subscription for the authenticated caller session."""
    session_id = _session_id(identity)
    session = await _live_session(session_id)
    mode = EventSubscriptionMode.ONCE if request.once else EventSubscriptionMode.EVERY
    subscription = await _service().subscribe(session, request.event_type, mode, request.narrowing)
    return _subscription_dto(
        subscription.id,
        subscription.event_type,
        subscription.mode,
        subscription.narrowing_json,
        subscription.created_at,
    )


@router.get("", response_model=list[EventSubscriptionDTO])
async def list_subscriptions(
    identity: CallerIdentity = Depends(carried_caller),
) -> list[EventSubscriptionDTO]:
    """List only subscriptions owned by the authenticated caller session."""
    subscriptions = await _service().list_for(_session_id(identity))
    return [
        _subscription_dto(
            subscription.id,
            subscription.event_type,
            subscription.mode,
            subscription.narrowing_json,
            subscription.created_at,
        )
        for subscription in subscriptions
    ]


@router.delete("/{subscription_id}", response_model=EventSubscriptionMutationResponseDTO)
async def unsubscribe(
    subscription_id: str,
    identity: CallerIdentity = Depends(carried_caller),
) -> EventSubscriptionMutationResponseDTO:
    """Withdraw one subscription only when it belongs to the caller session."""
    removed = await _service().unsubscribe(_session_id(identity), subscription_id)
    return EventSubscriptionMutationResponseDTO(removed=removed)
