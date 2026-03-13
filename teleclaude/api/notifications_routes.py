from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, HTTPException, Query

if TYPE_CHECKING:
    from teleclaude.events.db import EventDB

_event_db: EventDB | None = None

router = APIRouter()


def configure(event_db: EventDB | None) -> None:
    """Wire event DB; called from APIServer."""
    global _event_db
    _event_db = event_db


@router.get("/api/notifications")
async def list_notifications(
    level: int | None = Query(None),
    domain: str | None = Query(None),
    human_status: str | None = Query(None),
    agent_status: str | None = Query(None),
    visibility: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    rows = await _event_db.list_notifications(
        level=level,
        domain=domain,
        human_status=human_status,
        agent_status=agent_status,
        visibility=visibility,
        since=since,
        limit=limit,
        offset=offset,
    )
    return rows


@router.get("/api/notifications/{notification_id}")
async def get_notification(notification_id: int) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    row = await _event_db.get_notification(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


@router.patch("/api/notifications/{notification_id}/seen")
async def mark_notification_seen(
    notification_id: int,
    unseen: bool = Query(False),
) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    status = "unseen" if unseen else "seen"
    ok = await _event_db.update_human_status(notification_id, status)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/api/notifications/{notification_id}/claim")
async def claim_notification(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    agent_id = body.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    ok = await _event_db.update_agent_status(notification_id, "claimed", agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.patch("/api/notifications/{notification_id}/status")
async def update_notification_status(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    status = body.get("status")
    agent_id = body.get("agent_id")
    if not isinstance(status, str) or not status:
        raise HTTPException(status_code=400, detail="status required")
    if not isinstance(agent_id, str) or not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required")
    ok = await _event_db.update_agent_status(notification_id, status, agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/api/notifications/{notification_id}/resolve")
async def resolve_notification(
    notification_id: int,
    body: dict[str, object] = Body(...),  # guard: loose-dict - API boundary
) -> object:
    if _event_db is None:
        raise HTTPException(status_code=503, detail="Event DB not available")
    ok = await _event_db.resolve_notification(notification_id, dict(body))
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}
