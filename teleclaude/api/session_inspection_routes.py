"""Read-only HTTP endpoint for one session's stored record."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Final, assert_never

from fastapi import APIRouter, Depends, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CallerIdentity,
    caller_for_role_resolution,
    carried_caller,
    principal_for_carried_caller,
)
from teleclaude.api.session_ownership import LocalOwnership, RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_route_helpers import http_exception_for_relay_failure
from teleclaude.config.machine import config
from teleclaude.constants import SessionTarget
from teleclaude.core.command_dispatch import RelayFailure, relay_caller_read
from teleclaude.core.db import SessionRecordAbsent, SessionRecordFound, SessionRecordOutsideReach, db
from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.core.relayed_intake import RelayRead
from teleclaude.core.session_inspection import OUTSIDE_REACH_DETAIL_TEMPLATE, curated_view, inspect_local

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_RELAY_FAILURE_EVENT: Final[str] = "inspect_session.relay_failure"
_REMOTE_UNAVAILABLE_DETAIL: Final[str] = "Remote session inspection is unavailable"
_REMOTE_INVALID_DETAIL: Final[str] = "Peer answered session inspection with an invalid record"
_NOT_FOUND_DETAIL_TEMPLATE: Final[str] = "session {session_id} not found"
_NOT_A_SESSION_DETAIL_TEMPLATE: Final[str] = "not a TeleClaude session; terminal identity is {identity}"
_NO_TERMINAL_IDENTITY: Final[str] = "absent (no principal or email is carried)"
_STATE = SimpleNamespace(client=None, cache=None)

router = APIRouter()


def configure(client: AdapterClient | None = None, cache: DaemonCache | None = None) -> None:
    """Wire the peer transport and the cached peer snapshots used to locate a session."""
    if client is not None:
        _STATE.client = client
    if cache is not None:
        _STATE.cache = cache


@router.get("/sessions/{session_id}", response_model=None)
async def inspect_session_endpoint(
    session_id: str,
    full: bool = Query(False, description="Show the complete stored record instead of the grouped detail"),
    identity: CallerIdentity = Depends(carried_caller),
) -> JsonDict:
    """Show one session's stored record under the caller's listing reach."""
    target_session_id = _resolve_target(session_id, identity)
    record = await _read_record(target_session_id, identity)
    return record if full else curated_view(record)


def _resolve_target(session_id: str, identity: CallerIdentity) -> str:
    if session_id != SessionTarget.SELF:
        return session_id
    if identity.session_id:
        return identity.session_id
    raise HTTPException(
        status_code=400,
        detail=_NOT_A_SESSION_DETAIL_TEMPLATE.format(
            identity=identity.principal or identity.email or _NO_TERMINAL_IDENTITY
        ),
    )


async def _read_record(session_id: str, identity: CallerIdentity) -> JsonDict:
    ownership = await resolve_session_ownership(session_id, db=db, cache=_STATE.cache)
    match ownership:
        case None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL_TEMPLATE.format(session_id=session_id))
        case RemoteOwnership():
            return await _relay_record(session_id, ownership.computer, identity)
        case LocalOwnership():
            return await _read_local_record(session_id, identity)
        case _:
            assert_never(ownership)


async def _read_local_record(session_id: str, identity: CallerIdentity) -> JsonDict:
    read = await inspect_local(caller_for_role_resolution(identity), session_id)
    match read:
        case SessionRecordFound(values=values):
            return values
        case SessionRecordOutsideReach():
            raise HTTPException(
                status_code=403,
                detail=OUTSIDE_REACH_DETAIL_TEMPLATE.format(session_id=session_id, computer=config.computer.name),
            )
        case SessionRecordAbsent():
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL_TEMPLATE.format(session_id=session_id))
        case _:
            assert_never(read)


async def _relay_record(session_id: str, target_computer: str, identity: CallerIdentity) -> JsonDict:
    if _STATE.client is None:
        raise HTTPException(status_code=503, detail=_REMOTE_UNAVAILABLE_DETAIL)
    principal = principal_for_carried_caller(identity, required=True)
    try:
        data: JsonValue = await relay_caller_read(
            _STATE.client,
            target_computer,
            RelayRead.SESSION_RECORD.value,
            principal=principal,
            session_id=session_id,
        )
    except RelayFailure as exc:
        logger.error(_RELAY_FAILURE_EVENT, computer=target_computer, exc_info=True)
        raise http_exception_for_relay_failure(exc) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=_REMOTE_INVALID_DETAIL)
    return data
