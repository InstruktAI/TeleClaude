"""Small shared helpers for session API routes."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.models import JsonDict, MessageMetadata
from teleclaude.types.commands import CloseSessionCommand


def build_metadata(*, origin: str = "terminal", **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def close_accepted(command: CloseSessionCommand, *, location_label: str | None = None) -> JSONResponse:
    """Return the uniform accepted response for a close command."""
    message = f"Session {command.session_id} closing"
    if location_label is not None:
        message = f"{message} on {location_label}"
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "message": message, "completion_event": command.completion_event},
    )


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
