"""Remote session operations over Redis request/response."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.session_create_launch import (
    effective_launch_agent,
    resolve_enabled_agent,
    resolve_launch_kind,
)
from teleclaude.api.sessions_actions_routes import _rewrite_codex_next_startup_message
from teleclaude.api_models import CreateSessionRequest, CreateSessionResponseDTO
from teleclaude.constants import EVENT_END_SESSION, EVENT_NEW_SESSION
from teleclaude.core.adapter_client._remote import RemoteDispatchError
from teleclaude.core.models import JsonDict, MessageMetadata, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.origins import InputOrigin
from teleclaude.core.shell_identity import require_shell_safe_identifier

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

REMOTE_CREATE_TIMEOUT_SECONDS = 30.0
REMOTE_CLOSE_TIMEOUT_SECONDS = 30.0

logger = get_logger(__name__)


def is_remote_target(computer: str | None, local_computer: str) -> bool:
    """Return whether a request targets a peer computer rather than this one."""
    return bool(computer) and computer not in ("local", local_computer)


def is_remote_create_target(computer: str, local_computer: str) -> bool:
    """Return whether a create request targets a peer computer."""
    return is_remote_target(computer, local_computer)


def _remote_session_fields(envelope_text: str) -> tuple[str, str]:
    try:
        envelope_obj: object = json.loads(envelope_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Remote session creation returned invalid JSON") from exc

    if not isinstance(envelope_obj, dict):
        raise HTTPException(status_code=502, detail="Remote session creation returned invalid response")

    envelope = cast(JsonDict, envelope_obj)
    if envelope.get("status") == "error":
        error = envelope.get("error")
        detail = str(error) if error else "Remote session creation failed"
        raise HTTPException(status_code=502, detail=detail)

    if envelope.get("status") != "success":
        raise HTTPException(status_code=502, detail="Remote session creation returned invalid status")

    data_obj = envelope.get("data")
    if not isinstance(data_obj, dict):
        raise HTTPException(status_code=502, detail="Remote session creation returned invalid data")

    session_id = data_obj.get("session_id")
    tmux_session_name = data_obj.get("tmux_session_name")
    if not session_id or not tmux_session_name:
        raise HTTPException(status_code=502, detail="Remote session creation omitted transport fields")

    try:
        safe_tmux_session_name = require_shell_safe_identifier(tmux_session_name, "remote tmux_session_name")
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Remote session creation returned invalid transport fields"
        ) from exc

    return str(session_id), safe_tmux_session_name


async def dispatch_session_create_to_peer(
    client: AdapterClient | None,
    target_computer: str,
    request: CreateSessionRequest,
    *,
    identity_metadata: MessageMetadata,
) -> CreateSessionResponseDTO:
    """Create a session on a peer computer through Redis request/response.

    ``identity_metadata`` carries the initiating client's resolved origin and
    identity (human_email/human_role/system_role/job), produced by the same
    preparation the local create path uses. Forwarding it lets the peer's
    identity gate pass and gives the created session a truthful origin — the
    computer that initiated travels separately as the transport ``initiator``.
    """
    if client is None:
        raise HTTPException(status_code=503, detail="Remote session creation is unavailable")

    thinking_mode = request.thinking_mode or "slow"
    validated_agent = resolve_enabled_agent(request.agent) if request.agent else None
    launch_kind = resolve_launch_kind(request)
    if launch_kind == SessionLaunchKind.AGENT_RESUME and not request.agent:
        raise HTTPException(status_code=400, detail="agent required for agent_resume")
    if launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE and request.message is None:
        raise HTTPException(status_code=400, detail="message required for agent_then_message")

    effective_agent = None
    if launch_kind != SessionLaunchKind.EMPTY:
        effective_agent = effective_launch_agent(validated_agent)
    launch_message = request.message
    if launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE and request.message:
        if effective_agent is None:
            raise HTTPException(status_code=400, detail="agent required for agent_then_message")
        launch_message = _rewrite_codex_next_startup_message(
            request.message,
            effective_agent=effective_agent,
        )

    metadata = MessageMetadata(
        origin=identity_metadata.origin,
        project_path=request.project_path,
        human_email=identity_metadata.human_email,
        human_role=identity_metadata.human_role,
        system_role=identity_metadata.system_role,
        job=identity_metadata.job,
        launch_intent=SessionLaunchIntent(
            kind=launch_kind,
            agent=effective_agent,
            thinking_mode=thinking_mode,
            message=launch_message,
            native_session_id=request.native_session_id,
        ),
    )

    try:
        message_id = await client.send_request(target_computer, EVENT_NEW_SESSION, metadata)
        response_text = await client.read_response(
            message_id,
            timeout=REMOTE_CREATE_TIMEOUT_SECONDS,
            target_computer=target_computer,
        )
        session_id, tmux_session_name = _remote_session_fields(response_text)
    except HTTPException as exc:
        if exc.status_code >= 500:
            logger.warning(
                "Remote session creation failed",
                target_computer=target_computer,
                status_code=exc.status_code,
                detail=exc.detail,
            )
        raise exc
    except TimeoutError as exc:
        logger.warning(
            "Remote session creation timed out",
            target_computer=target_computer,
            timeout=REMOTE_CREATE_TIMEOUT_SECONDS,
        )
        raise HTTPException(status_code=504, detail="Remote session creation timed out") from exc
    except (RuntimeError, OSError) as exc:
        logger.error(
            "Remote session creation transport unavailable",
            target_computer=target_computer,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="Remote session creation transport unavailable") from exc

    return CreateSessionResponseDTO(
        status="success",
        session_id=session_id,
        tmux_session_name=tmux_session_name,
        computer=target_computer,
        agent=effective_agent,
    )


async def dispatch_session_close_to_peer(
    client: AdapterClient | None,
    target_computer: str,
    session_id: str,
) -> None:
    """Close a session on a peer computer through Redis request/response.

    The peer maps the ``end_session`` command to its own ``CloseSessionCommand``
    and runs it against its local session store — the authority for sessions it
    owns. This daemon never holds the peer's session row, so the close must be
    forwarded rather than resolved locally.
    """
    if client is None:
        raise HTTPException(status_code=503, detail="Remote session close is unavailable")

    metadata = MessageMetadata(origin=InputOrigin.TERMINAL.value)
    try:
        await client.dispatch_remote_command(
            target_computer,
            EVENT_END_SESSION,
            metadata,
            session_id=session_id,
            timeout=REMOTE_CLOSE_TIMEOUT_SECONDS,
        )
    except RemoteDispatchError as exc:
        logger.warning(
            "Remote session close rejected",
            target_computer=target_computer,
            session_id=session_id,
            detail=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TimeoutError as exc:
        logger.warning(
            "Remote session close timed out",
            target_computer=target_computer,
            session_id=session_id,
            timeout=REMOTE_CLOSE_TIMEOUT_SECONDS,
        )
        raise HTTPException(status_code=504, detail="Remote session close timed out") from exc
    except (RuntimeError, OSError) as exc:
        logger.error(
            "Remote session close transport unavailable",
            target_computer=target_computer,
            session_id=session_id,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="Remote session close transport unavailable") from exc
