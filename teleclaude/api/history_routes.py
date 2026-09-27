"""Authenticated local and federated history search route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from teleclaude.api.auth import (
    CallerIdentity,
    caller_from_carried_identity,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.api.session_remote import is_remote_target
from teleclaude.config import config
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core.command_dispatch import RemoteDispatchError, parse_remote_dispatch_data_diagnosed
from teleclaude.core.models import JsonDict, MessageMetadata
from teleclaude.history.search_payload import HistorySearchPayload
from teleclaude.history.service import (
    HistoryDetailPayload,
    HistoryRelayCommand,
    HistoryShowRequest,
    build_history_detail_payload,
    build_history_search_payload,
    parse_history_agents,
)
from teleclaude.mirrors.store import history_access_for_caller
from teleclaude.utils.transcript_discovery import SessionId

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

REMOTE_HISTORY_SEARCH_FAILURE_EVENT = "history_search.remote_failure"
REMOTE_HISTORY_SEARCH_FAILURE_DETAIL = "Remote history search failed"
REMOTE_HISTORY_SEARCH_TIMEOUT_DETAIL = "Remote history search timed out"
REMOTE_HISTORY_SHOW_FAILURE_EVENT = "history_show.remote_failure"
REMOTE_HISTORY_SHOW_FAILURE_DETAIL = "Remote history show failed"
REMOTE_HISTORY_SHOW_TIMEOUT_DETAIL = "Remote history show timed out"
_REMOTE_HISTORY_RELAY_UNAVAILABLE_DETAIL = "Remote history relay is unavailable"
_REMOTE_HISTORY_SHOW_UNAVAILABLE_DETAIL = "Remote history show is unavailable"
_REQUESTED_SESSION_ID_LOG_FIELD = "requested_session_id"
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


def _raise_remote_history_request_failure(
    *,
    event: str,
    detail: str,
    computer: str,
    log_fields: dict[str, str],
    cause: Exception,
) -> NoReturn:
    """Log a remote-history failure and return a translated HTTP error."""
    logger.error(event, computer=computer, **log_fields, exc_info=True)
    raise HTTPException(status_code=500, detail=detail) from cause


async def _dispatch_remote_history_request[Response](
    *,
    computer: str,
    command: HistoryRelayCommand,
    metadata: MessageMetadata,
    response_adapter: TypeAdapter[Response],
    failure_event: str,
    failure_detail: str,
    timeout_detail: str,
    failure_log_fields: dict[str, str],
) -> Response:
    """Relay one history request and translate failures at the route boundary."""
    client = _STATE.client
    if client is None:
        raise HTTPException(status_code=503, detail=_REMOTE_HISTORY_RELAY_UNAVAILABLE_DETAIL)
    try:
        message_id = await client.send_request(computer, command.value, metadata)
        response_text = await client.read_response(message_id, target_computer=computer)
        data = await parse_remote_dispatch_data_diagnosed(
            client,
            response_text,
            target_computer=computer,
            command=command.value,
        )
        return response_adapter.validate_python(data)
    except HTTPException:
        raise
    except RemoteDispatchError as exc:
        _raise_remote_history_request_failure(
            event=failure_event,
            computer=computer,
            detail=str(exc),
            log_fields=failure_log_fields,
            cause=exc,
        )
    except (TimeoutError, RedisTimeoutError) as exc:
        _raise_remote_history_request_failure(
            event=failure_event,
            computer=computer,
            detail=timeout_detail,
            log_fields=failure_log_fields,
            cause=exc,
        )
    except (OSError, RedisError) as exc:
        _raise_remote_history_request_failure(
            event=failure_event,
            computer=computer,
            detail=failure_detail,
            log_fields=failure_log_fields,
            cause=exc,
        )


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
            caller_principal=principal_for_carried_caller(caller),
        )
        return await _dispatch_remote_history_request(
            computer=target_computer,
            command=HistoryRelayCommand.SEARCH,
            metadata=metadata,
            response_adapter=TypeAdapter(HistorySearchPayload),
            failure_event=REMOTE_HISTORY_SEARCH_FAILURE_EVENT,
            failure_detail=REMOTE_HISTORY_SEARCH_FAILURE_DETAIL,
            timeout_detail=REMOTE_HISTORY_SEARCH_TIMEOUT_DETAIL,
            failure_log_fields={},
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
    computer: str | None = None,
    caller: CallerIdentity = Depends(carried_caller),
) -> HistoryDetailPayload:
    """Resolve and return one local or peer-scoped history detail."""
    access = history_access_for_caller(caller_from_carried_identity(caller))
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

    if is_remote_target(computer, config.computer.name):
        if _STATE.client is None:
            raise HTTPException(status_code=503, detail=_REMOTE_HISTORY_SHOW_UNAVAILABLE_DETAIL)
        target_computer = computer or _NO_REMOTE_COMPUTER
        request = HistoryShowRequest(
            session_id=parsed_session_id,
            agent=agent,
            thinking=thinking,
            raw=raw,
        )
        metadata = MessageMetadata(
            origin_metadata=cast(JsonDict, request),
            human_email=caller.email,
            human_role=caller.human_role,
            caller_principal=principal_for_carried_caller(caller),
        )
        response_adapter: TypeAdapter[HistoryDetailPayload | None] = TypeAdapter(HistoryDetailPayload | None)
        payload = await _dispatch_remote_history_request(
            computer=target_computer,
            command=HistoryRelayCommand.SHOW,
            metadata=metadata,
            response_adapter=response_adapter,
            failure_event=REMOTE_HISTORY_SHOW_FAILURE_EVENT,
            failure_detail=REMOTE_HISTORY_SHOW_FAILURE_DETAIL,
            timeout_detail=REMOTE_HISTORY_SHOW_TIMEOUT_DETAIL,
            failure_log_fields={_REQUESTED_SESSION_ID_LOG_FIELD: parsed_session_id},
        )
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail=_HISTORY_DETAIL_NOT_FOUND.format(session_id=parsed_session_id),
            )
        return payload

    payload: HistoryDetailPayload | None = await asyncio.to_thread(
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
