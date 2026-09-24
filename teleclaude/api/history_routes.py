"""Authenticated local and federated history search route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter

from teleclaude.api.auth import (
    CallerIdentity,
    caller_from_verified_identity,
    clearance_history_search,
    clearance_history_show,
    principal_for_verified_caller,
)
from teleclaude.api.session_remote import is_remote_target
from teleclaude.config import config
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core.command_dispatch import RemoteDispatchError, parse_remote_dispatch_data_diagnosed
from teleclaude.core.models import JsonDict, MessageMetadata
from teleclaude.history.service import (
    HistoryDetailPayload,
    HistorySearchPayload,
    build_history_detail_payload,
    build_history_search_payload,
    parse_history_agents,
)
from teleclaude.mirrors.store import history_access_for_caller
from teleclaude.utils.transcript_discovery import SessionId

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

REMOTE_HISTORY_SEARCH_COMMAND = "history_search"
REMOTE_HISTORY_SEARCH_FAILURE_EVENT = "history_search.remote_failure"
REMOTE_HISTORY_SEARCH_FAILURE_DETAIL = "Remote history search failed"
REMOTE_HISTORY_SEARCH_TIMEOUT_DETAIL = "Remote history search timed out"
_NO_REMOTE_COMPUTER = ""
_HISTORY_DETAIL_NOT_FOUND = "No transcript found for session '{session_id}'"
_UNKNOWN_AGENT_FILTER = "Unknown agent filter: {agent}"

_STATE = SimpleNamespace(client=None)
logger = get_logger(__name__)
router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire the peer transport used for federated search."""
    if client is not None:
        _STATE.client = client


def _raise_remote_history_search_failure(
    *,
    computer: str,
    detail: str,
    cause: Exception,
) -> NoReturn:
    """Log a remote-search failure and return a translated HTTP error."""
    logger.error(REMOTE_HISTORY_SEARCH_FAILURE_EVENT, computer=computer, exc_info=True)
    raise HTTPException(status_code=500, detail=detail) from cause


@router.get("/history/search")
async def search_history(
    q: str = "",
    agent: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    computer: str | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    caller: CallerIdentity = Depends(clearance_history_search),
) -> HistorySearchPayload:
    """Search local or peer mirrors through the authenticated daemon boundary."""
    resolved_caller = caller_from_verified_identity(caller)
    access = history_access_for_caller(resolved_caller)
    if access is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)

    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_UNKNOWN_AGENT_FILTER.format(agent=agent)) from exc

    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail="Remote history search is unavailable")
        target_computer = computer or _NO_REMOTE_COMPUTER
        origin_metadata = cast(
            JsonDict,
            {
                "q": q,
                "agent": agent,
                "limit": limit,
                "include_workers": include_workers,
                "identity": identity,
                "project": project,
            },
        )
        metadata = MessageMetadata(
            origin_metadata=origin_metadata,
            human_email=caller.email,
            human_role=caller.human_role,
            caller_principal=principal_for_verified_caller(caller),
        )
        try:
            message_id = await _STATE.client.send_request(
                target_computer,
                REMOTE_HISTORY_SEARCH_COMMAND,
                metadata,
            )
            response_text = await _STATE.client.read_response(
                message_id,
                target_computer=target_computer,
            )
            data = await parse_remote_dispatch_data_diagnosed(
                _STATE.client,
                response_text,
                target_computer=target_computer,
                command=REMOTE_HISTORY_SEARCH_COMMAND,
            )
            return TypeAdapter(HistorySearchPayload).validate_python(data)
        except HTTPException:
            raise
        except RemoteDispatchError as exc:
            _raise_remote_history_search_failure(
                computer=target_computer,
                detail=str(exc),
                cause=exc,
            )
        except TimeoutError as exc:
            _raise_remote_history_search_failure(
                computer=target_computer,
                detail=REMOTE_HISTORY_SEARCH_TIMEOUT_DETAIL,
                cause=exc,
            )
        except Exception as exc:
            _raise_remote_history_search_failure(
                computer=target_computer,
                detail=REMOTE_HISTORY_SEARCH_FAILURE_DETAIL,
                cause=exc,
            )

    return await asyncio.to_thread(
        build_history_search_payload,
        computer=config.computer.name,
        query=q,
        agents=agents,
        limit=limit,
        access=access,
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
    caller: CallerIdentity = Depends(clearance_history_show),
) -> HistoryDetailPayload:
    """Resolve and return one caller-scoped history detail."""
    access = history_access_for_caller(caller_from_verified_identity(caller))
    if access is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    try:
        parsed_session_id = str(SessionId(session_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown agent filter: {agent}") from exc

    payload = await asyncio.to_thread(
        build_history_detail_payload,
        parsed_session_id,
        access=access,
        agents=agents,
        include_thinking=thinking,
        raw=raw,
    )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=_HISTORY_DETAIL_NOT_FOUND.format(session_id=parsed_session_id),
        )
    return payload
