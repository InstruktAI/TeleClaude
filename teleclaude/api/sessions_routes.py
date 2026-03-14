"""Session management endpoints (list, create, delete, send-message)."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CLEARANCE_SESSIONS_END,
    CLEARANCE_SESSIONS_LIST,
    CLEARANCE_SESSIONS_SEND,
    CLEARANCE_SESSIONS_START,
    CallerIdentity,
)
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    SendMessageRequest,
    SessionDTO,
)
from teleclaude.config import config
from teleclaude.constants import format_system_message
from teleclaude.core import command_handlers
from teleclaude.core.agents import assert_agent_enabled, get_default_agent, get_known_agents
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    SessionLifecycleContext,
    TeleClaudeEvents,
    parse_command_string,
)
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.models import (
    MessageMetadata,
    SessionLaunchIntent,
    SessionLaunchKind,
    SessionMetadata,
    SessionSnapshot,
)
from teleclaude.core.origins import InputOrigin

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_client: AdapterClient | None = None
_cache: DaemonCache | None = None

router = APIRouter()


def configure(
    client: AdapterClient | None = None,
    cache: DaemonCache | None = None,
) -> None:
    """Wire client and cache; called from APIServer."""
    global _client, _cache
    if client is not None:
        _client = client
    _cache = cache


def _build_metadata(**kwargs: object) -> MessageMetadata:
    """Build API boundary metadata."""
    return MessageMetadata(origin=InputOrigin.API.value, **kwargs)


def _filter_sessions_by_role(request: Request, sessions: list[SessionSnapshot]) -> list[SessionSnapshot]:
    """Apply role-based visibility filtering to session list.

    Only filters when identity headers are present (web interface).
    TUI/tool clients without headers see all sessions (existing behavior).
    """
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")

    # No identity headers = TUI/tool client, return all
    if not email:
        return sessions

    # Admin sees everything
    if role == "admin":
        return sessions

    # Member sees own + shared
    if role == "member":
        return [s for s in sessions if s.human_email == email or s.visibility == "shared"]

    # Contributor/newcomer/unknown: own sessions only
    return [s for s in sessions if s.human_email == email]


def _format_direct_conversation_intro(
    *,
    caller_session_id: str,
    caller_label: str,
    caller_computer: str,
    message_text: str,
) -> str:
    """Wrap the first direct-conversation message with the required operating instructions."""
    body = "\n".join(
        [
            f'The direct conversation is active with "{caller_label}" ({caller_session_id}) on {caller_computer}.',
            "",
            "Rules:",
            "- Set a Note To Self anchor before engaging.",
            "- Do not use `telec sessions send` for follow-up messages.",
            "- Just talk in normal output; your turn-complete output is delivered automatically.",
            "- Do not acknowledge, echo, or narrate. Reply only if it changes the peer's next action.",
            "",
            "Protocol:",
            "- Agent-only default: `PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in prose`",
            "- Human-observed default: `PROTOCOL: L1 prose, human in loop`",
            "",
            "Peer introduction:",
            message_text.strip(),
        ]
    )
    return format_system_message("Direct Conversation", body)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    computer: str | None = None,
    include_closed: bool = Query(False, alias="closed"),
    all_sessions: bool = Query(False, alias="all"),
    job: str | None = Query(None, alias="job"),
    identity: CallerIdentity = Depends(CLEARANCE_SESSIONS_LIST),
) -> list[SessionDTO]:
    """List sessions from local storage and remote cache.

    Applies role-based filtering when identity headers are present
    (web interface requests). TUI/tool clients without headers see all.

    Args:
        request: FastAPI request (for identity headers)
        computer: Optional filter by computer name
        include_closed: Include closed sessions

    Returns:
        List of session summaries (merged local + cached remote)
    """
    try:
        local_sessions = await command_handlers.list_sessions(include_closed=include_closed)

        # No cache: serve local sessions only (respect computer filter)
        if not _cache:
            if computer and computer not in ("local", config.computer.name):
                return []
            merged = local_sessions
        elif computer:
            # With cache, merge local + cached sessions
            cached_filtered = _cache.get_sessions(computer)
            if computer in ("local", config.computer.name):
                by_id = {s.session_id: s for s in local_sessions}
                for s in cached_filtered:
                    by_id.setdefault(s.session_id, s)
                merged = list(by_id.values())
            else:
                merged = cached_filtered
        else:
            cached_sessions = _cache.get_sessions()
            by_id = {s.session_id: s for s in local_sessions}
            for s in cached_sessions:
                by_id.setdefault(s.session_id, s)
            merged = list(by_id.values())

        # Telec tool default: show sessions spawned by current caller only.
        caller_session_id = request.headers.get("x-caller-session-id")
        if caller_session_id and not all_sessions:
            merged = [s for s in merged if s.initiator_session_id == caller_session_id]

        # Role-based visibility filtering (only when identity headers present)
        merged = _filter_sessions_by_role(request, merged)

        # Job filter: narrows existing visibility results
        if job:
            merged = [
                s for s in merged
                if s.session_metadata is not None
                and s.session_metadata.job == job
            ]

        return [SessionDTO.from_core(s, computer=s.computer) for s in merged]
    except Exception as e:
        logger.error("list_sessions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity = Depends(CLEARANCE_SESSIONS_START),
) -> CreateSessionResponseDTO:
    """Create new local session.

    Note: Remote session creation via API is not yet implemented;
    all sessions are created on the local machine regardless of
    the computer field in the request.

    Args:
        request: CreateSessionRequest model

    Returns:
        CreateSessionResponseDTO
    """
    # Normalize request into internal command.

    effective_human_role = request.human_role or identity.human_role
    channel_metadata: dict[str, str] | None = None
    if request.human_email or effective_human_role:
        channel_metadata = {}
        if request.human_email:
            channel_metadata["human_email"] = request.human_email
        if effective_human_role:
            channel_metadata["human_role"] = effective_human_role
    if request.direct and not identity.session_id:
        raise HTTPException(
            status_code=400,
            detail="direct mode requires caller session identity",
        )

    if identity.session_id and not identity.session_id.startswith("web:"):
        channel_metadata = channel_metadata or {}
        channel_metadata["initiator_session_id"] = identity.session_id

    incoming_meta = request.metadata
    request_session_meta: SessionMetadata | None = None
    if incoming_meta:
        request_session_meta = SessionMetadata(
            system_role=str(incoming_meta.get("system_role") or "") or None,
            job=str(incoming_meta.get("job") or "") or None,
        )
    metadata = _build_metadata(
        title=request.title or "Untitled",
        project_path=request.project_path,
        subdir=request.subdir,
        channel_metadata=channel_metadata,
        session_metadata=request_session_meta,
        # launch_intent and auto_command logic will be simplified or moved
    )

    # Extract title from message if not provided (legacy behavior)
    title = request.title
    if not title and request.message and request.message.startswith("/"):
        title = request.message
    title = title or "Untitled"

    effective_thinking_mode = request.thinking_mode or "slow"
    direct_caller_session = None

    def _resolve_enabled_agent(requested_agent: str | None) -> str:
        if requested_agent:
            try:
                return assert_agent_enabled(requested_agent)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return get_default_agent()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    validated_request_agent: str | None = None
    if request.agent:
        validated_request_agent = _resolve_enabled_agent(request.agent)

    if request.auto_command:
        command_name, command_args = parse_command_string(request.auto_command)
        normalized_command = (command_name or "").lower()
        known_agents = set(get_known_agents())

        resume_aliases = {f"{agent}_resume" for agent in known_agents}

        if normalized_command in known_agents:
            _resolve_enabled_agent(normalized_command)
        elif normalized_command in resume_aliases:
            _resolve_enabled_agent(normalized_command.removesuffix("_resume"))
        elif normalized_command in {"agent", "agent_then_message", "agent_resume", "agent_restart"}:
            auto_command_agent = command_args[0] if command_args else validated_request_agent
            if auto_command_agent:
                _resolve_enabled_agent(auto_command_agent)

    def _effective_launch_agent() -> str:
        if validated_request_agent:
            return validated_request_agent
        return _resolve_enabled_agent(None)

    launch_intent = None
    if not request.auto_command:
        launch_kind = SessionLaunchKind(request.launch_kind)
        if launch_kind == SessionLaunchKind.AGENT and request.message:
            launch_kind = SessionLaunchKind.AGENT_THEN_MESSAGE

        if launch_kind == SessionLaunchKind.EMPTY:
            launch_intent = SessionLaunchIntent(kind=SessionLaunchKind.EMPTY)
        elif launch_kind == SessionLaunchKind.AGENT_RESUME:
            if not request.agent:
                raise HTTPException(status_code=400, detail="agent required for agent_resume")
            effective_agent = validated_request_agent or _resolve_enabled_agent(request.agent)
            launch_intent = SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_RESUME,
                agent=effective_agent,
                thinking_mode=effective_thinking_mode,
                native_session_id=request.native_session_id,
            )
        elif launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
            if request.message is None:
                raise HTTPException(status_code=400, detail="message required for agent_then_message")
            direct_message = request.message
            if request.direct and identity.session_id:
                direct_caller_session = await db.get_session(identity.session_id)
                caller_label = (
                    direct_caller_session.title
                    if direct_caller_session and direct_caller_session.title
                    else identity.session_id
                )
                caller_computer = (
                    direct_caller_session.computer_name if direct_caller_session else config.computer.name
                )
                direct_message = _format_direct_conversation_intro(
                    caller_session_id=identity.session_id,
                    caller_label=caller_label,
                    caller_computer=caller_computer,
                    message_text=request.message,
                )
            effective_agent = _effective_launch_agent()
            launch_intent = SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                agent=effective_agent,
                thinking_mode=effective_thinking_mode,
                message=direct_message,
            )
        else:
            effective_agent = _effective_launch_agent()
            launch_intent = SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent=effective_agent,
                thinking_mode=effective_thinking_mode,
            )

    auto_command = request.auto_command
    if not auto_command and launch_intent:
        if launch_intent.kind == SessionLaunchKind.AGENT:
            auto_command = f"agent {launch_intent.agent} {launch_intent.thinking_mode}"
        elif launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
            quoted_message = shlex.quote(launch_intent.message or "")
            auto_command = (
                f"agent_then_message {launch_intent.agent} {launch_intent.thinking_mode} {quoted_message}"
            )
        elif launch_intent.kind == SessionLaunchKind.AGENT_RESUME:
            if launch_intent.native_session_id:
                auto_command = f"agent_resume {launch_intent.agent} {launch_intent.native_session_id}"
            else:
                auto_command = f"agent_resume {launch_intent.agent}"

    auto_command_source = "request" if request.auto_command else ("derived" if launch_intent else "none")
    logger.info(
        "create_session request: computer=%s project=%s agent=%s thinking_mode=%s launch_kind=%s "
        "native_session_id=%s auto_command=%s auto_command_source=%s",
        request.computer,
        request.project_path,
        request.agent,
        request.thinking_mode,
        request.launch_kind,
        request.native_session_id,
        auto_command,
        auto_command_source,
    )

    # Update metadata with derived fields
    metadata.title = title
    metadata.launch_intent = launch_intent
    metadata.auto_command = auto_command
    cmd = CommandMapper.map_api_input(
        "new_session",
        {"skip_listener_registration": request.skip_listener_registration},
        metadata,
    )

    try:
        data = await get_command_service().create_session(cmd)

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
            logger.error(
                "create_session missing required fields (session_id=%s, tmux_session_name=%s)",
                session_id,
                tmux_session_name,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to create session: missing session_id or tmux_session_name",
            )

        if request.direct and identity.session_id:
            from teleclaude.core.session_listeners import create_or_reuse_direct_link, unregister_listener

            await unregister_listener(
                target_session_id=str(session_id),
                caller_session_id=identity.session_id,
            )

            caller_session = direct_caller_session or await db.get_session(identity.session_id)
            target_session = await db.get_session(str(session_id))
            caller_label = (
                caller_session.title if caller_session and caller_session.title else identity.session_id
            )
            target_label = target_session.title if target_session and target_session.title else title
            caller_computer = caller_session.computer_name if caller_session else config.computer.name
            target_computer = target_session.computer_name if target_session else config.computer.name
            await create_or_reuse_direct_link(
                caller_session_id=identity.session_id,
                target_session_id=str(session_id),
                caller_name=caller_label,
                target_name=target_label,
                caller_computer=caller_computer,
                target_computer=target_computer,
            )

        return CreateSessionResponseDTO(
            status="success",
            session_id=str(session_id),
            tmux_session_name=str(tmux_session_name),
            agent=launch_intent.agent if launch_intent else None,
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e


@router.delete("/sessions/{session_id}")
async def end_session(
    request: Request,
    session_id: str,
    computer: str = Query(...),
    identity: CallerIdentity = Depends(CLEARANCE_SESSIONS_END),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """End session - local sessions only (remote management uses RPC transport)."""
    from teleclaude.api.session_access import check_session_access

    user_agent = request.headers.get("user-agent", "no-ua")
    identity_email = request.headers.get("x-web-email", "none")
    logger.info(
        "DELETE /sessions/%s (ua=%s, identity=%s)",
        session_id,
        user_agent,
        identity_email,
    )

    await check_session_access(request, session_id, require_owner=True)
    try:
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        close_context = SessionLifecycleContext(session_id=session_id)
        if session.closed_at or session.lifecycle_status == "closed":
            event_bus.emit(TeleClaudeEvents.SESSION_CLOSED, close_context)
            return {
                "status": "success",
                "message": f"Session {session_id} already closed",
            }

        if session.lifecycle_status != "closing":
            await db.update_session(session_id, lifecycle_status="closing")

        event_bus.emit(TeleClaudeEvents.SESSION_CLOSE_REQUESTED, close_context)
        return JSONResponse(  # pyright: ignore[reportReturnType]
            status_code=202,
            content={
                "status": "accepted",
                "message": f"Session {session_id} closing",
            },
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error("Failed to end session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e


@router.post("/sessions/{session_id}/message")
async def send_message_endpoint(
    http_request: Request,
    session_id: str,
    request: SendMessageRequest,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(CLEARANCE_SESSIONS_SEND),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send message to session."""
    from teleclaude.api.session_access import check_session_access
    from teleclaude.core.session_listeners import (
        close_link_for_member,
        create_or_reuse_direct_link,
        get_peer_members,
        resolve_link_for_sender_target,
        unregister_listener,
    )

    await check_session_access(http_request, session_id)
    try:
        target_session = None
        if request.message:
            target_session = await db.get_session(session_id)
            if not target_session:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            if target_session.closed_at or target_session.lifecycle_status in {"closed", "closing"}:
                raise HTTPException(status_code=409, detail=f"Session {session_id} is closed")

        if request.close_link:
            if not identity.session_id:
                raise HTTPException(status_code=400, detail="close_link requires caller session identity")

            active_link = await resolve_link_for_sender_target(
                sender_session_id=identity.session_id,
                target_session_id=session_id,
            )
            if not active_link:
                return {"status": "error", "message": "no active direct link found"}

            if request.message:
                metadata = _build_metadata()
                cmd = CommandMapper.map_api_input(
                    "message",
                    {"session_id": session_id, "text": request.message},
                    metadata,
                )
                await get_command_service().process_message(cmd)

            closed_link_id = await close_link_for_member(
                caller_session_id=identity.session_id,
                target_session_id=session_id,
            )
            return {"status": "success", "mode": "direct", "action": "closed", "link_id": closed_link_id}

        if not request.message:
            raise HTTPException(status_code=400, detail="message required")

        message_text = request.message
        metadata = _build_metadata()
        if request.direct:
            if not identity.session_id:
                raise HTTPException(status_code=400, detail="direct mode requires caller session identity")

            caller_session = await db.get_session(identity.session_id)
            if target_session is None:
                target_session = await db.get_session(session_id)
            caller_label = (
                caller_session.title if caller_session and caller_session.title else identity.session_id
            )
            target_label = target_session.title if target_session and target_session.title else session_id
            caller_computer = caller_session.computer_name if caller_session else config.computer.name
            target_computer = target_session.computer_name if target_session else config.computer.name

            link_ctx = await resolve_link_for_sender_target(
                sender_session_id=identity.session_id,
                target_session_id=session_id,
            )
            if link_ctx:
                return {
                    "status": "error",
                    "mode": "direct",
                    "link_id": link_ctx[0].link_id,
                    "message": (
                        "A direct link is already active with this peer. "
                        "We agreed not to use send during direct conversation "
                        "as it obfuscates the exchange from the observer. "
                        "Your turn-complete output is automatically shared — just talk."
                    ),
                }

            await unregister_listener(
                target_session_id=session_id,
                caller_session_id=identity.session_id,
            )

            link, _ = await create_or_reuse_direct_link(
                caller_session_id=identity.session_id,
                target_session_id=session_id,
                caller_name=caller_label,
                target_name=target_label,
                caller_computer=caller_computer,
                target_computer=target_computer,
            )
            link_ctx = await resolve_link_for_sender_target(
                sender_session_id=identity.session_id,
                target_session_id=session_id,
            )
            if not link_ctx:
                raise HTTPException(status_code=500, detail="failed to resolve direct link")

            _, members = link_ctx
            message_text = _format_direct_conversation_intro(
                caller_session_id=identity.session_id,
                caller_label=caller_label,
                caller_computer=caller_computer,
                message_text=message_text,
            )
            peers = await get_peer_members(link_id=link.link_id, sender_session_id=identity.session_id)
            delivery_targets = [peer.session_id for peer in peers] or [session_id]
            delivered_to = 0
            for target_id in delivery_targets:
                target_for_delivery = await db.get_session(target_id)
                if not target_for_delivery:
                    logger.info("Skipping direct delivery to missing session %s", target_id)
                    continue
                if target_for_delivery.closed_at or target_for_delivery.lifecycle_status in {
                    "closed",
                    "closing",
                }:
                    logger.info("Skipping direct delivery to closed session %s", target_id)
                    continue
                cmd = CommandMapper.map_api_input(
                    "message",
                    {"session_id": target_id, "text": message_text},
                    metadata,
                )
                await get_command_service().process_message(cmd)
                delivered_to += 1

            if delivered_to == 0:
                return {
                    "status": "error",
                    "mode": "direct",
                    "link_id": link.link_id,
                    "message": "No active target sessions available for delivery",
                }

            return {
                "status": "success",
                "mode": "direct",
                "link_id": link.link_id,
                "link_state": "created",
                "delivered_to": delivered_to,
                "members": len(members),
            }

        if identity.session_id:
            existing_link = await resolve_link_for_sender_target(
                sender_session_id=identity.session_id,
                target_session_id=session_id,
            )
            if existing_link:
                return {
                    "status": "error",
                    "mode": "direct",
                    "link_id": existing_link[0].link_id,
                    "message": (
                        "A direct link is active with this peer. "
                        "We agreed not to use send during direct conversation "
                        "as it obfuscates the exchange from the observer. "
                        "Your turn-complete output is automatically shared — just talk."
                    ),
                }

        cmd = CommandMapper.map_api_input(
            "message",
            {"session_id": session_id, "text": message_text},
            metadata,
        )
        await get_command_service().process_message(cmd)
        return {"status": "success", "mode": "work"}
    except SessionMessageRejectedError as exc:
        raise HTTPException(status_code=exc.http_status_code, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_message failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e

