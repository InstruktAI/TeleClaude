"""FastAPI routes for mirror detail and transcript drill-down."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from teleclaude.api.auth import (
    CallerIdentity,
    caller_from_verified_identity,
    clearance_history_show,
)
from teleclaude.constants import LOGIN_REQUIRED_DETAIL

from .store import get_mirror, history_access_for_caller

router = APIRouter(prefix="/api/mirrors", tags=["mirrors"])


class MirrorDetailResponse(TypedDict):
    """Wire format for a full mirror detail response."""

    session_id: str
    computer: str
    agent: str
    project: str
    title: str
    conversation_text: str
    message_count: int
    timestamp_start: str | None
    timestamp_end: str | None
    coverage_state: str
    shrink_refused_at: str | None


@router.get("/{session_id}")
async def get_mirror_route(
    session_id: str,
    caller: CallerIdentity = Depends(clearance_history_show),
) -> MirrorDetailResponse:
    """Fetch a single mirror by session id."""
    access = history_access_for_caller(caller_from_verified_identity(caller))
    if access is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    mirror = await asyncio.to_thread(get_mirror, native_session_id=session_id, access=access)
    if mirror is None or mirror.native_session_id is None:
        raise HTTPException(status_code=404, detail="Mirror not found")
    return {
        "session_id": mirror.native_session_id,
        "computer": mirror.computer or "",
        "agent": mirror.agent,
        "project": mirror.project_path or "",
        "title": mirror.title or "",
        "conversation_text": mirror.conversation_text,
        "message_count": mirror.message_count,
        "timestamp_start": mirror.timestamp_start,
        "timestamp_end": mirror.timestamp_end,
        "coverage_state": mirror.coverage_state.value,
        "shrink_refused_at": mirror.shrink_refused_at,
    }


@router.get("/{session_id}/transcript")
async def get_mirror_transcript_route(
    session_id: str,
    caller: CallerIdentity = Depends(clearance_history_show),
) -> PlainTextResponse:
    """Return the raw transcript file content for a mirror."""
    access = history_access_for_caller(caller_from_verified_identity(caller))
    if access is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    mirror = await asyncio.to_thread(get_mirror, native_session_id=session_id, access=access)
    if mirror is None:
        raise HTTPException(status_code=404, detail="Mirror not found")
    transcript_path = mirror.metadata.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise HTTPException(status_code=404, detail="Transcript path missing")
    path = Path(transcript_path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript file not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"))
