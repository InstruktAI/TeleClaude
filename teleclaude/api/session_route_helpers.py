"""Small shared helpers for session API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, principal_for_carried_caller
from teleclaude.config.machine import config
from teleclaude.core.command_dispatch import RelayFailure, RemoteDispatchReason, dispatch_command, is_remote_target
from teleclaude.core.db import db
from teleclaude.core.models import JsonDict, JsonValue, MessageMetadata
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.types.commands import InternalCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


def build_metadata(*, origin: str = "terminal", **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def close_accepted(receipt: SerializedOperation) -> JSONResponse:
    """Return the operation receipt as the close command's 202 response.

    The receipt's own ``computer`` field already names the owning computer,
    so no separate location label is needed here.
    """
    return JSONResponse(status_code=202, content=dict(receipt))


def http_exception_for_relay_failure(error: RelayFailure) -> HTTPException:
    """Translate a typed relay failure at the API boundary."""
    if error.reason is RemoteDispatchReason.NOT_FOUND:
        status_code = 404
    elif error.reason is RemoteDispatchReason.UNREACHABLE:
        status_code = 504
    elif error.reason is RemoteDispatchReason.REFUSED_BY_TARGET:
        status_code = 403
    else:
        status_code = 502
    return HTTPException(status_code=status_code, detail=str(error))


async def dispatch_caller_command(
    client: AdapterClient | None,
    command: InternalCommand,
    identity: CallerIdentity,
) -> JsonValue | None:
    """Dispatch a caller's command with the verified principal required by remote targets."""
    principal = principal_for_carried_caller(
        identity,
        required=is_remote_target(command.computer, config.computer.name),
    )
    return await dispatch_command(client, command, principal=principal)


async def resolve_created_session_transport(data: JsonDict) -> tuple[str, str]:
    """Resolve mandatory session creation response fields."""
    session_id = data.get("session_id")
    tmux_session_name = data.get("tmux_session_name")
    if session_id and not tmux_session_name:
        try:
            session = await db.get_session(str(session_id))
        except RuntimeError:
            session = None
        if session:
            tmux_session_name = session.tmux_session_name
    if not session_id or not tmux_session_name:
        get_logger(__name__).error(
            "create_session missing required fields (session_id=%s, tmux_session_name=%s)",
            session_id,
            tmux_session_name,
        )
        raise HTTPException(status_code=500, detail="Failed to create session: missing session_id or tmux_session_name")
    return str(session_id), str(tmux_session_name)
