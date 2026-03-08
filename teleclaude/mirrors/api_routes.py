"""FastAPI routes for mirror search and transcript drill-down."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from teleclaude.core.agents import AgentName

from .store import get_mirror, search_mirrors

router = APIRouter(prefix="/api/mirrors", tags=["mirrors"])


class MirrorSearchResponseRow(TypedDict):
    session_id: str
    computer: str
    agent: str
    project: str
    title: str
    sort_timestamp: str
    timestamp: str
    topic: str


class MirrorDetailResponse(TypedDict):
    session_id: str
    computer: str
    agent: str
    project: str
    title: str
    conversation_text: str
    message_count: int
    timestamp_start: str | None
    timestamp_end: str | None


def _parse_agent_filter(agent: str) -> list[AgentName]:
    if agent == "all":
        return list(AgentName)
    values: list[AgentName] = []
    for raw in agent.split(","):
        value = raw.strip().lower()
        if not value:
            continue
        values.append(AgentName(value))
    return values


@router.get("/search")
async def search_mirror_routes(
    q: str,
    agent: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[MirrorSearchResponseRow]:
    """Search local mirrors via FTS5."""
    try:
        agents = _parse_agent_filter(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown agent filter: {agent}") from exc

    results = await asyncio.to_thread(search_mirrors, q, agents, limit=limit)
    return [
        {
            "session_id": result.session_id,
            "computer": result.computer,
            "agent": result.agent,
            "project": result.project,
            "title": result.title,
            "sort_timestamp": result.sort_timestamp,
            "timestamp": result.timestamp,
            "topic": result.topic,
        }
        for result in results
    ]


@router.get("/{session_id}")
async def get_mirror_route(session_id: str) -> MirrorDetailResponse:
    """Fetch a single mirror by session id."""
    mirror = await asyncio.to_thread(get_mirror, session_id)
    if mirror is None:
        raise HTTPException(status_code=404, detail="Mirror not found")
    return {
        "session_id": mirror.session_id,
        "computer": mirror.computer,
        "agent": mirror.agent,
        "project": mirror.project,
        "title": mirror.title,
        "conversation_text": mirror.conversation_text,
        "message_count": mirror.message_count,
        "timestamp_start": mirror.timestamp_start,
        "timestamp_end": mirror.timestamp_end,
    }


@router.get("/{session_id}/transcript")
async def get_mirror_transcript_route(session_id: str) -> PlainTextResponse:
    """Return the raw transcript file content for a mirror."""
    mirror = await asyncio.to_thread(get_mirror, session_id)
    if mirror is None:
        raise HTTPException(status_code=404, detail="Mirror not found")
    transcript_path = mirror.metadata.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        raise HTTPException(status_code=404, detail="Transcript path missing")
    path = Path(transcript_path).expanduser()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript file not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"))
