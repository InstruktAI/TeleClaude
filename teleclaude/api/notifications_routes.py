"""Notification polling and update endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, HTTPException, Query, Request

if TYPE_CHECKING:
    from teleclaude.events.db import EventDB

_EVENT_DB: dict[str, EventDB | None] = {"value": None}

router = APIRouter()


def configure(event_db: EventDB | None) -> None:
    """Wire event DB; called from APIServer."""
    _EVENT_DB["value"] = event_db


def _require_event_db() -> EventDB:
    """Return the configured event DB or raise service unavailable."""
    event_db = _EVENT_DB["value"]
    if event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    return event_db


def _parse_optional_int(value: str | None, field_name: str) -> int | None:
    """Parse an optional integer query parameter."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be an integer") from exc


def _parse_bounded_int(value: str | None, field_name: str, *, default: int, minimum: int, maximum: int) -> int:
    """Parse and validate a bounded integer query parameter."""
    parsed = default if value is None else _parse_optional_int(value, field_name)
    assert parsed is not None
    if not minimum <= parsed <= maximum:
        raise HTTPException(status_code=422, detail=f"{field_name} must be between {minimum} and {maximum}")
    return parsed


@router.get("/api/notifications")
async def list_notifications(
    request: Request,
) -> object:
    """List notification rows with optional filters."""
    level = _parse_optional_int(request.query_params.get("level"), "level")
    limit = _parse_bounded_int(request.query_params.get("limit"), "limit", default=50, minimum=1, maximum=200)
    offset = _parse_bounded_int(request.query_params.get("offset"), "offset", default=0, minimum=0, maximum=2000000)
    rows = await _require_event_db().list_notifications(
        level=level,
        domain=request.query_params.get("domain"),
        human_status=request.query_params.get("human_status"),
        agent_status=request.query_params.get("agent_status"),
        visibility=request.query_params.get("visibility"),
        since=request.query_params.get("since"),
        limit=limit,
        offset=offset,
    )
    return rows


@router.get("/api/notifications/{notification_id}")
async def get_notification(notification_id: int) -> object:
    """Fetch a single notification row by id."""
    row = await _require_event_db().get_notification(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


@router.patch("/api/notifications/{notification_id}/seen")
async def mark_notification_seen(
    notification_id: int,
    unseen: bool = Query(False),
) -> object:
    """Toggle the human seen/unseen state for a notification."""
    status = "unseen" if unseen else "seen"
    ok = await _require_event_db().update_human_status(notification_id, status)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/api/notifications/{notification_id}/claim")
async def claim_notification(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    """Claim a notification for an agent."""
    agent_id = body.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    ok = await _require_event_db().update_agent_status(notification_id, "claimed", agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.patch("/api/notifications/{notification_id}/status")
async def update_notification_status(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    """Update the agent-side status for a notification."""
    status = body.get("status")
    agent_id = body.get("agent_id")
    if not isinstance(status, str) or not status:
        raise HTTPException(status_code=400, detail="status required")
    if not isinstance(agent_id, str) or not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    ok = await _require_event_db().update_agent_status(notification_id, status, agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/api/notifications/{notification_id}/resolve")
async def resolve_notification(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    """Resolve a notification with a structured resolution payload."""
    ok = await _require_event_db().resolve_notification(notification_id, dict(body))
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}
