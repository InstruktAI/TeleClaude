"""Authenticated local and federated history search route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter, ValidationError

from teleclaude.api.auth import (
    CallerIdentity,
    caller_from_carried_identity,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.api.session_remote import is_remote_target
from teleclaude.api.session_route_helpers import http_exception_for_relay_failure
from teleclaude.config.machine import config
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core.command_dispatch import RelayFailure, RemoteDispatchReason, relay_caller_read
from teleclaude.core.models import JsonDict
from teleclaude.history.search_payload import HistorySearchPayload
from teleclaude.history.service import (
    HistoryDetailPayload,
    HistoryRelayCommand,
    HistoryShowRequest,
    build_history_detail_payload,
    build_history_search_payload,
    history_caller_is_identified,
    parse_history_agents,
    resolve_history_reach,
)
from teleclaude.utils.transcript_discovery import SessionId

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

REMOTE_HISTORY_SEARCH_FAILURE_EVENT = "history_search.remote_failure"
REMOTE_HISTORY_SHOW_FAILURE_EVENT = "history_show.remote_failure"
_REMOTE_HISTORY_RELAY_UNAVAILABLE_DETAIL = "Remote history relay is unavailable"
_REMOTE_HISTORY_SHOW_UNAVAILABLE_DETAIL = "Remote history show is unavailable"
_REQUESTED_SESSION_ID_LOG_FIELD = "requested_session_id"
_NO_REMOTE_COMPUTER = ""
_HISTORY_DETAIL_NOT_FOUND = "No transcript found for session '{session_id}'"
_UNKNOWN_AGENT_FILTER = "Unknown agent filter: {agent}"
_QUERY_FIELD = "q"
_AGENT_FIELD = "agent"
_LIMIT_FIELD = "limit"
_INCLUDE_WORKERS_FIELD = "include_workers"
_IDENTITY_FIELD = "identity"
_PROJECT_FIELD = "project"

_STATE = SimpleNamespace(client=None)
logger = get_logger(__name__)
router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire the peer transport used for federated search."""
    if client is not None:
        _STATE.client = client


def _log_remote_history_request_failure(
    *,
    event: str,
    computer: str,
    log_fields: dict[str, str],
) -> None:
    """Log a remote history failure with its command-specific event."""
    logger.error(event, computer=computer, **log_fields, exc_info=True)


async def _dispatch_remote_history_request[Response](
    *,
    computer: str,
    command: HistoryRelayCommand,
    principal: str,
    request: JsonDict,
    response_adapter: TypeAdapter[Response],
    failure_event: str,
    failure_log_fields: dict[str, str],
) -> Response:
    """Relay one history request and translate failures at the route boundary."""
    client = _STATE.client
    if client is None:
        raise HTTPException(status_code=503, detail=_REMOTE_HISTORY_RELAY_UNAVAILABLE_DETAIL)
    try:
        data = await relay_caller_read(
            client,
            computer,
            command.value,
            principal=principal,
            request=request,
        )
        return response_adapter.validate_python(data)
    except HTTPException:
        raise
    except RelayFailure as exc:
        _log_remote_history_request_failure(
            event=failure_event,
            computer=computer,
            log_fields=failure_log_fields,
        )
        raise http_exception_for_relay_failure(exc) from exc
    except ValidationError as exc:
        relay_error = RelayFailure(
            computer=computer,
            command=command.value,
            reason=RemoteDispatchReason.PEER_ERROR,
            detail=str(exc),
        )
        _log_remote_history_request_failure(
            event=failure_event,
            computer=computer,
            log_fields=failure_log_fields,
        )
        raise http_exception_for_relay_failure(relay_error) from exc


@router.get("/history/search")
async def search_history(
    q: str = "",
    agent: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    computer: str | None = None,
    include_workers: bool = False,
    identity: str | None = None,
    project: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> HistorySearchPayload:
    """Search local or peer mirrors through the authenticated daemon boundary."""
    resolved_caller = caller_from_carried_identity(caller)
    if not history_caller_is_identified(resolved_caller):
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)

    try:
        agents = parse_history_agents(agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_UNKNOWN_AGENT_FILTER.format(agent=agent)) from exc

    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail="Remote history search is unavailable")
        principal = principal_for_carried_caller(caller, required=True)
        target_computer = computer or _NO_REMOTE_COMPUTER
        request: JsonDict = {
            _QUERY_FIELD: q,
            _AGENT_FIELD: agent,
            _LIMIT_FIELD: limit,
            _INCLUDE_WORKERS_FIELD: include_workers,
            _IDENTITY_FIELD: identity,
            _PROJECT_FIELD: project,
        }
        return await _dispatch_remote_history_request(
            computer=target_computer,
            command=HistoryRelayCommand.SEARCH,
            principal=principal,
            request=request,
            response_adapter=TypeAdapter(HistorySearchPayload),
            failure_event=REMOTE_HISTORY_SEARCH_FAILURE_EVENT,
            failure_log_fields={},
        )

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
    computer: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> HistoryDetailPayload:
    """Resolve and return one local or peer-scoped history detail."""
    resolved_caller = caller_from_carried_identity(caller)
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

    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail=_REMOTE_HISTORY_SHOW_UNAVAILABLE_DETAIL)
        principal = principal_for_carried_caller(caller, required=True)
        target_computer = computer or _NO_REMOTE_COMPUTER
        request = HistoryShowRequest(
            session_id=parsed_session_id,
            agent=agent,
            thinking=thinking,
            raw=raw,
        )
        response_adapter: TypeAdapter[HistoryDetailPayload | None] = TypeAdapter(HistoryDetailPayload | None)
        payload = await _dispatch_remote_history_request(
            computer=target_computer,
            command=HistoryRelayCommand.SHOW,
            principal=principal,
            request=cast(JsonDict, request),
            response_adapter=response_adapter,
            failure_event=REMOTE_HISTORY_SHOW_FAILURE_EVENT,
            failure_log_fields={_REQUESTED_SESSION_ID_LOG_FIELD: parsed_session_id},
        )
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=_HISTORY_DETAIL_NOT_FOUND.format(session_id=parsed_session_id),
            )
        return payload

    reach = await asyncio.to_thread(resolve_history_reach, resolved_caller)
    if reach is None:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    payload: HistoryDetailPayload | None = await asyncio.to_thread(
        build_history_detail_payload,
        parsed_session_id,
        reach=reach,
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
