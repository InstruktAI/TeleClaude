"""Authenticated history search and show routes; a request naming another computer is answered there."""

from __future__ import annotations

import asyncio
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, carried_caller
from teleclaude.caller_identity import CliCaller
from teleclaude.config.machine import config
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core.command_dispatch import RELAY_REQUEST_TIMEOUT_S
from teleclaude.core.runtime_events import publish_runtime_error
from teleclaude.history.search_payload import HistorySearchPayload
from teleclaude.history.service import (
    HistoryDetailPayload,
    build_history_detail_payload,
    build_history_search_payload,
    history_caller_is_identified,
    parse_history_agents,
    resolve_history_reach,
)
from teleclaude.mirrors.errors import MirrorIdentityAmbiguityError
from teleclaude.utils.transcript_discovery import SessionId

_HISTORY_DETAIL_NOT_FOUND = "No transcript found for session '{session_id}'"
_UNKNOWN_AGENT_FILTER = "Unknown agent filter: {agent}"

router = APIRouter()
logger = get_logger(__name__)


async def _identity_resolved_caller(caller: CallerIdentity) -> CliCaller:
    """Resolve the carried caller off the event loop, waiting no longer than the relay budget for an executor slot."""
    return await asyncio.wait_for(
        asyncio.to_thread(caller_for_role_resolution, caller), timeout=RELAY_REQUEST_TIMEOUT_S
    )


@router.get("/history/search")
async def search_history(
    q: str = "",
    agent: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> HistorySearchPayload:
    """Search this computer's history mirrors within the caller's reach."""
    resolved_caller = await _identity_resolved_caller(caller)
    if not history_caller_is_identified(resolved_caller):
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)

    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_UNKNOWN_AGENT_FILTER.format(agent=agent)) from exc

    reach = await asyncio.to_thread(resolve_history_reach, resolved_caller)
    if reach is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    return await asyncio.to_thread(
        build_history_search_payload,
        computer=config.computer.name,
        query=q,
        agents=agents,
        limit=limit,
        reach=reach,
        include_workers=include_workers,
        identity=identity,
        project=project,
    )


@router.get("/history/show/{session_id}")
async def show_history(
    session_id: str,
    agent: str = Query(default="all"),
    thinking: bool = False,
    raw: bool = False,
    caller: CallerIdentity = Depends(carried_caller),
) -> HistoryDetailPayload:
    """Resolve and return one history detail within the caller's reach."""
    resolved_caller = await _identity_resolved_caller(caller)
    if not history_caller_is_identified(resolved_caller):
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    try:
        parsed_session_id = str(SessionId(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown agent filter: {agent}") from exc

    reach = await asyncio.to_thread(resolve_history_reach, resolved_caller)
    if reach is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    transcript_mismatches: list[tuple[str, str]] = []
    try:
        payload: HistoryDetailPayload | None = await asyncio.to_thread(
            build_history_detail_payload,
            parsed_session_id,
            reach=reach,
            agents=agents,
            include_thinking=thinking,
            raw=raw,
            on_format_mismatch=lambda agent_name, path, _error: transcript_mismatches.append((agent_name, path.name)),
        )
    except MirrorIdentityAmbiguityError as exc:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
    for agent_name, filename in transcript_mismatches:
        try:
            await publish_runtime_error(
                source="transcript_reader",
                message=(
                    f"Transcript parser can't read {agent_name} session file {filename} — file shape may have changed "
                    "in the agent CLI. Output/summary/title for this session will be empty until the parser is updated."
                ),
                severity="warning",
            )
        except Exception:
            logger.warning("Transcript format error publication failed", exc_info=True)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=_HISTORY_DETAIL_NOT_FOUND.format(session_id=parsed_session_id),
        )
    return payload
