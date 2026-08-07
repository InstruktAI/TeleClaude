"""Session management endpoints (list, create, delete, send-message)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import (
    CallerIdentity,
    clearance_sessions_end,
    clearance_sessions_list,
    clearance_sessions_send,
    clearance_sessions_start,
)
from teleclaude.api.codex_startup_message import _rewrite_codex_next_startup_message
from teleclaude.api.session_access import check_session_access
from teleclaude.api.session_create_launch import (
    effective_launch_agent,
    resolve_enabled_agent,
    resolve_launch_kind,
)
from teleclaude.api.session_ownership import RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_remote import is_remote_create_target, is_remote_target
from teleclaude.api.sessions_actions_routes import _infer_role_and_slug_from_message, guard_generic_create_session
from teleclaude.api.sessions_responses import active_direct_link_response as _active_direct_link_response
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    SendMessageRequest,
    SendMessageResponseDTO,
    SessionDTO,
)
from teleclaude.config import config
from teleclaude.config.loader import load_global_config
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core import command_handlers
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.conversation_messages import (
    MACHINE_ROLE_LABELS as _MACHINE_ROLE_LABELS,
)
from teleclaude.core.conversation_messages import (
    MachineRoleLabel,
    format_identity_header,
    format_peer_header,
    is_conversation_bridge_message,
    is_orchestrator_dispatch_message,
)
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError, UnidentifiableCallerError
from teleclaude.core.models import JsonDict, MessageMetadata, SessionLaunchIntent, SessionLaunchKind, SessionSnapshot
from teleclaude.core.models._adapter import TerminalOriginMetadata, WebOriginMetadata
from teleclaude.core.next_machine.session_hold import hold_todo_for_manual_session_close
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    close_link_for_member,
    create_or_reuse_direct_link,
    get_peer_members,
    register_listener,
    resolve_link_for_sender_target,
)
from teleclaude.core.session_status import is_session_terminal as _terminal

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import Session
from teleclaude.types.commands import CloseSessionCommand

logger = get_logger(__name__)

_CONFIG_UNSET = object()

_STATE = SimpleNamespace(client=None, cache=None)

router = APIRouter()


def configure(
    client: AdapterClient | None | object = _CONFIG_UNSET,
    cache: DaemonCache | None | object = _CONFIG_UNSET,
) -> None:
    """Wire client and cache; called from APIServer."""
    if client is not _CONFIG_UNSET:
        _STATE.client = client
    if cache is not _CONFIG_UNSET:
        _STATE.cache = cache


def _build_metadata(*, origin: str = InputOrigin.TERMINAL.value, **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


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
    if role == HUMAN_ROLE_ADMIN:
        return sessions

    # Member sees own + shared
    if role == HUMAN_ROLE_MEMBER:
        return [s for s in sessions if s.human_email == email or s.visibility == "shared"]

    # Contributor/newcomer/unknown: own sessions only
    return [s for s in sessions if s.human_email == email]


def _check_remote_session_owner(request: Request, ownership: RemoteOwnership) -> None:
    """Verify owner-only access against a cached peer-owned session."""
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")

    if not email:
        return
    if role == HUMAN_ROLE_ADMIN:
        return
    if ownership.snapshot.human_email == email:
        return

    raise HTTPException(status_code=403, detail="Forbidden: not session owner")


def _close_accepted(command: CloseSessionCommand, *, location_label: str | None = None) -> JSONResponse:
    message = f"Session {command.session_id} closing"
    if location_label is not None:
        message = f"{message} on {location_label}"
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": message,
            "completion_event": command.completion_event,
        },
    )


def enrich_human_names(dtos: list[SessionDTO]) -> list[SessionDTO]:
    """Resolve human_name from people config for each DTO with a human_email."""
    people = load_global_config().people
    name_by_email: dict[str, str] = {}
    for person in people:
        if person.email:
            name_by_email[person.email.lower()] = person.name
    return [
        dto.model_copy(update={"human_name": name_by_email[dto.human_email.lower()]})
        if dto.human_email and dto.human_email.lower() in name_by_email
        else dto
        for dto in dtos
    ]


def _format_direct_conversation_intro(
    *,
    caller_session_id: str,
    caller_computer: str,
    message_text: str,
) -> str:
    """Wrap the first direct-conversation message with the required operating instructions."""
    header = format_peer_header(
        sender_session_id=caller_session_id,
        sender_computer=caller_computer,
    )
    body = "\n".join(
        [
            "Rules:",
            "- Do not use `telec sessions send` for follow-up messages.",
            "- Just talk in normal output; your turn-complete output is delivered automatically.",
            "- Default emit state is false. Reply only if your output changes the peer's next action.",
            "- Valid replies answer a question, report a blocker or decision point, provide new information, or deliver a result or artifact.",
            "- The bracketed peer header and per-segment markers are framing, not content; only act on what the segments say.",
            "- Do not acknowledge, echo, narrate, or send status-only output such as `idle` or `done`.",
            "",
            "Protocol:",
            "- Agent-only default: `PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in prose`",
            "- Human-observed default: `PROTOCOL: L1 prose, human in loop`",
            "",
            "Peer introduction:",
            message_text.strip(),
        ]
    )
    return f"{header}\n\n{body}"


def _extract_initiator_session_id(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> str | None:
    """Extract initiator session ID from caller identity."""
    if request.direct and not identity.session_id:
        raise HTTPException(
            status_code=400,
            detail="direct mode requires caller session identity",
        )

    if identity.session_id and not identity.session_id.startswith("web:"):
        return identity.session_id
    return None


def _extract_session_role_fields(
    metadata: JsonDict | None,
) -> tuple[str | None, str | None]:
    """Extract system_role and job from request metadata dict."""
    if not metadata:
        return None, None
    system_role = str(metadata.get("system_role") or "") or None
    job = str(metadata.get("job") or "") or None
    return system_role, job


def _resolve_origin(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> tuple[str, str | None, Mapping[str, object] | None]:
    """Resolve origin, caller_email, and origin_metadata from request and identity.

    Daemon-internal callers (e.g. WhatsApp handler) may supply origin via top-level
    request fields or nested inside the metadata dict.  When neither is present,
    origin is derived from identity context (terminal vs web).

    Returns (origin, caller_email, origin_metadata).
    """
    explicit_origin = request.origin
    explicit_origin_meta: Mapping[str, object] | None = request.origin_metadata
    # API client pass-through: origin may be nested inside request.metadata
    if not explicit_origin and request.metadata and "origin" in request.metadata:
        explicit_origin = str(request.metadata["origin"])
        raw_meta = request.metadata.get("origin_metadata")
        if isinstance(raw_meta, dict) and not explicit_origin_meta:
            explicit_origin_meta = raw_meta

    caller_email = identity.email
    if explicit_origin:
        return explicit_origin, caller_email, explicit_origin_meta

    origin = InputOrigin.TERMINAL.value
    if request.human_email:
        origin = InputOrigin.WEB.value
        caller_email = request.human_email
    typed_origin: WebOriginMetadata | TerminalOriginMetadata | None = None
    if caller_email:
        if origin == InputOrigin.WEB.value:
            typed_origin = WebOriginMetadata(email=caller_email)
        else:
            typed_origin = TerminalOriginMetadata(email=caller_email)
    return origin, caller_email, typed_origin


async def _build_direct_launch_message(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> tuple[str, Session | None]:
    """Format the initial direct-conversation message and return caller session."""
    if not request.direct or not identity.session_id or request.message is None:
        return request.message or "", None

    caller_session = await db.get_session(identity.session_id)
    caller_computer = caller_session.computer_name if caller_session else config.computer.name
    return (
        _format_direct_conversation_intro(
            caller_session_id=identity.session_id,
            caller_computer=caller_computer,
            message_text=request.message,
        ),
        caller_session,
    )


async def _build_launch_intent(
    request: CreateSessionRequest,
    identity: CallerIdentity,
    validated_request_agent: str | None,
    thinking_mode: str,
) -> tuple[SessionLaunchIntent | None, Session | None]:
    """Build the typed launch intent for a new session."""
    launch_kind = resolve_launch_kind(request)

    if launch_kind == SessionLaunchKind.EMPTY:
        return SessionLaunchIntent(kind=SessionLaunchKind.EMPTY), None

    if launch_kind == SessionLaunchKind.AGENT_RESUME:
        if not request.agent:
            raise HTTPException(status_code=400, detail="agent required for agent_resume")
        effective_agent = validated_request_agent or resolve_enabled_agent(request.agent)
        return (
            SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_RESUME,
                agent=effective_agent,
                thinking_mode=thinking_mode,
                native_session_id=request.native_session_id,
            ),
            None,
        )

    if launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
        if request.message is None:
            raise HTTPException(status_code=400, detail="message required for agent_then_message")
        effective_agent = effective_launch_agent(validated_request_agent)
        startup_message = _rewrite_codex_next_startup_message(
            request.message,
            effective_agent=effective_agent,
        )
        launch_request = (
            request.model_copy(update={"message": startup_message}) if startup_message != request.message else request
        )
        direct_message, caller_session = await _build_direct_launch_message(launch_request, identity)
        return (
            SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                agent=effective_agent,
                thinking_mode=thinking_mode,
                message=direct_message,
            ),
            caller_session,
        )

    return (
        SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=effective_launch_agent(validated_request_agent),
            thinking_mode=thinking_mode,
        ),
        None,
    )


def _resolve_effective_human_role(
    requested_human_role: str | None,
    authenticated_human_role: str | None,
) -> str | None:
    """Reject client role escalation unless the authenticated caller is already admin."""
    if requested_human_role is None:
        return authenticated_human_role
    if requested_human_role == authenticated_human_role:
        return authenticated_human_role
    if authenticated_human_role == HUMAN_ROLE_ADMIN:
        return requested_human_role
    raise HTTPException(status_code=403, detail="human_role override requires admin identity")


async def _link_direct_sessions(
    *,
    caller_session_id: str,
    target_session_id: str,
    caller_session: Session | None,
) -> None:
    """Create the direct link between caller and target sessions after creation.

    Does not touch listener records — the two subscription axes are orthogonal.
    Notification suppression while the link is active is enforced at delivery
    time in `_notify_listeners`. See `project/spec/session-subscriptions`.
    """
    resolved_caller_session = caller_session or await db.get_session(caller_session_id)
    target_session = await db.get_session(target_session_id)
    caller_label = (
        resolved_caller_session.title
        if resolved_caller_session and resolved_caller_session.title
        else caller_session_id
    )
    target_label = target_session.title if target_session and target_session.title else target_session_id
    caller_computer = resolved_caller_session.computer_name if resolved_caller_session else config.computer.name
    target_computer = target_session.computer_name if target_session else config.computer.name

    await create_or_reuse_direct_link(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        caller_name=caller_label,
        target_name=target_label,
        caller_computer=caller_computer,
        target_computer=target_computer,
    )


@dataclass(frozen=True)
class ListSessionsQuery:
    """Normalized query parameters for session listing."""

    computer: str | None = None
    include_closed: bool = False
    all_sessions: bool = False
    job: str | None = None


def _parse_list_sessions_query(
    computer: str | None = None,
    include_closed: bool = Query(False, alias="closed"),
    all_sessions: bool = Query(False, alias="all"),
    job: str | None = Query(None, alias="job"),
) -> ListSessionsQuery:
    """Collect list-sessions query parameters into one object."""
    return ListSessionsQuery(
        computer=computer,
        include_closed=include_closed,
        all_sessions=all_sessions,
        job=job,
    )


async def _prepare_create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> tuple[MessageMetadata, str | None, str | None, SessionLaunchIntent | None, Session | None]:
    """Prepare session creation metadata, initiator ID, and launch intent."""
    initiator_session_id = _extract_initiator_session_id(request, identity)

    origin, caller_email, origin_meta = _resolve_origin(request, identity)
    effective_human_role = _resolve_effective_human_role(request.human_role, identity.human_role)

    req_system_role, req_job = _extract_session_role_fields(request.metadata)

    # Infer role from slash command in message when metadata doesn't carry it (TUI create-door path).
    if not req_system_role:
        req_system_role, req_job, _ = _infer_role_and_slug_from_message(request.message)

    metadata = _build_metadata(
        origin=origin,
        project_path=request.project_path,
        subdir=request.subdir,
        human_email=caller_email,
        human_role=effective_human_role,
        origin_metadata=origin_meta,
        system_role=req_system_role,
        job=req_job,
    )

    initial_input = request.message

    effective_thinking_mode = request.thinking_mode or "slow"
    validated_request_agent = resolve_enabled_agent(request.agent) if request.agent else None
    launch_intent, direct_caller_session = await _build_launch_intent(
        request,
        identity,
        validated_request_agent,
        effective_thinking_mode,
    )
    metadata.launch_intent = launch_intent
    return metadata, initiator_session_id, initial_input, launch_intent, direct_caller_session


async def _resolve_created_session_transport(
    data: JsonDict,
) -> tuple[str, str]:
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
        logger.error(
            "create_session missing required fields (session_id=%s, tmux_session_name=%s)",
            session_id,
            tmux_session_name,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to create session: missing session_id or tmux_session_name",
        )
    return str(session_id), str(tmux_session_name)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    query: ListSessionsQuery = Depends(_parse_list_sessions_query),
    _identity: CallerIdentity = Depends(clearance_sessions_list),
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
        local_sessions = await command_handlers.list_sessions(include_closed=query.include_closed)

        # No cache: serve local sessions only (respect computer filter)
        if not _STATE.cache:
            if query.computer and query.computer not in ("local", config.computer.name):
                return []
            merged = local_sessions
        elif query.computer:
            # With cache, merge local + cached sessions
            cached_filtered = _STATE.cache.get_sessions(query.computer)
            if query.computer in ("local", config.computer.name):
                by_id = {s.session_id: s for s in local_sessions}
                for s in cached_filtered:
                    by_id.setdefault(s.session_id, s)
                merged = list(by_id.values())
            else:
                merged = cached_filtered
        else:
            cached_sessions = _STATE.cache.get_sessions()
            by_id = {s.session_id: s for s in local_sessions}
            for s in cached_sessions:
                by_id.setdefault(s.session_id, s)
            merged = list(by_id.values())

        # Telec tool default: show sessions spawned by current caller only.
        caller_session_id = request.headers.get("x-caller-session-id")
        if caller_session_id and not query.all_sessions:
            merged = [s for s in merged if s.initiator_session_id == caller_session_id]

        # Role-based visibility filtering (only when identity headers present)
        merged = _filter_sessions_by_role(request, merged)

        # Job filter: narrows existing visibility results
        if query.job:
            merged = [s for s in merged if s.job == query.job]

        dtos = [SessionDTO.from_core(s, computer=s.computer) for s in merged]
        return enrich_human_names(dtos)
    except Exception as e:
        logger.error("list_sessions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity = Depends(clearance_sessions_start),
) -> CreateSessionResponseDTO:
    """Create a new session on the local computer or a peer computer.

    Args:
        request: CreateSessionRequest model

    Returns:
        CreateSessionResponseDTO
    """
    logger.info(
        "create_session request: computer=%s project=%s agent=%s thinking_mode=%s launch_kind=%s native_session_id=%s",
        request.computer,
        request.project_path,
        request.agent,
        request.thinking_mode,
        request.launch_kind,
        request.native_session_id,
    )

    metadata, initiator_session_id, initial_input, launch_intent, direct_caller_session = await _prepare_create_session(
        request, identity
    )

    cmd = CommandMapper.map_api_input(
        "new_session",
        {
            "skip_listener_registration": request.skip_listener_registration,
            "initiator_session_id": initiator_session_id,
            "initial_input": initial_input,
            "title": request.title,
            "working_slug": _infer_role_and_slug_from_message(request.message)[2],
        },
        metadata,
        computer=request.computer,
    )

    await guard_generic_create_session(request, cmd, identity)

    try:
        result = await dispatch_command(_STATE.client, cmd)
        if not isinstance(result, dict):
            raise HTTPException(status_code=500, detail="Failed to create session")
        data = result
        session_id, tmux_session_name = await _resolve_created_session_transport(data)

        remote_create = is_remote_create_target(request.computer, config.computer.name)
        if request.direct and identity.session_id and not remote_create:
            await _link_direct_sessions(
                caller_session_id=identity.session_id,
                target_session_id=session_id,
                caller_session=direct_caller_session,
            )

        return CreateSessionResponseDTO(
            status="success",
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            computer=request.computer if remote_create else None,
            agent=launch_intent.agent if launch_intent else None,
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e


@router.delete("/sessions/{session_id}", status_code=202)
async def end_session(
    request: Request,
    session_id: str,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(clearance_sessions_end),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """End session via CloseSessionCommand through the command system."""
    user_agent = request.headers.get("user-agent", "no-ua")
    identity_email = request.headers.get("x-web-email", "none")
    logger.info(
        "DELETE /sessions/%s (computer=%s, ua=%s, identity=%s)",
        session_id,
        computer,
        user_agent,
        identity_email,
    )

    if computer and is_remote_target(computer, config.computer.name):
        ownership = await resolve_session_ownership(session_id, db=db, cache=_STATE.cache)
        target_computer: str | None = None
        if isinstance(ownership, RemoteOwnership):
            if ownership.computer != computer:
                raise HTTPException(status_code=404, detail="Session not found on requested computer")
            _check_remote_session_owner(request, ownership)
            target_computer = ownership.computer
        elif ownership is None:
            await check_session_access(request, session_id, require_owner=True)
            target_computer = computer

        if target_computer is not None:
            # ADR-0036: cross-host close carries no human-origin signal, so it does not hold (scoped out).
            cmd = CloseSessionCommand(session_id=session_id)
            cmd.computer = target_computer
            await dispatch_command(_STATE.client, cmd)
            return _close_accepted(cmd, location_label=target_computer)  # type: ignore[return-value]  # pyright: ignore[reportReturnType]

    await check_session_access(request, session_id, require_owner=True)
    # ADR-0036: only a human-initiated close holds the driven todo. A human
    # terminal/TUI/web caller has an empty identity.session_id; an agent
    # self-end / orchestrator child-end is token-authed (non-empty session_id)
    # and must not hold — the runner self-heals the stale active_runner link.
    if not identity.session_id:
        try:
            await hold_todo_for_manual_session_close(db, session_id)
        except Exception:
            logger.error("Manual session close hold interlock failed for %s", session_id, exc_info=True)

    try:
        cmd = CloseSessionCommand(session_id=session_id)
        await dispatch_command(_STATE.client, cmd)

        return _close_accepted(cmd)  # type: ignore[return-value]  # pyright: ignore[reportReturnType]
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error("Failed to end session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e


async def _machine_origin_marker(caller_session_id: str | None) -> str | None:
    """Build the identity header for a session-originated caller, or None for genuine human input.

    An absent ``caller_session_id`` is genuine human direct input (terminal/
    web/Telegram) and stays unmarked. A present ``caller_session_id`` means the
    message is session-originated and MUST carry an identity header: its role
    when resolvable, otherwise its active agent. An unresolved caller is refused.
    """
    if not caller_session_id:
        return None
    caller = await db.get_session(caller_session_id)
    if not caller:
        raise UnidentifiableCallerError(caller_session_id=caller_session_id)
    role_label = _MACHINE_ROLE_LABELS.get((caller.system_role or "").strip())
    return format_identity_header(
        role=role_label or MachineRoleLabel.AGENT,
        category=caller.active_agent.title() if not role_label and caller.active_agent else None,
        session_id=caller_session_id,
        computer=caller.computer_name if not role_label else caller.computer_name or config.computer.name,
    )


async def _wrap_message_with_origin(
    message_text: str,
    caller_session_id: str | None,
) -> str:
    """Prepend the caller's machine identity header when applicable.

    Skip when the message is already bracket-marked (TeleClaude bridge,
    Orchestrator dispatch) so we never double-wrap.
    """
    if is_conversation_bridge_message(message_text) or is_orchestrator_dispatch_message(message_text):
        return message_text
    header = await _machine_origin_marker(caller_session_id)
    if not header:
        return message_text
    return f"{header}\n\n{message_text}"


async def _process_api_message(
    session_id: str,
    message_text: str,
    metadata: MessageMetadata,
    computer: str | None = None,
) -> None:
    """Process a single API-originated message."""
    cmd = CommandMapper.map_api_input(
        "message",
        {"session_id": session_id, "text": message_text},
        metadata,
        computer=computer,
    )
    await dispatch_command(_STATE.client, cmd)


async def _load_target_session_for_message(
    session_id: str,
    message_text: str | None,
) -> Session | None:
    """Load and validate the target session when message delivery is requested."""
    if not message_text:
        return None

    target_session = await db.get_session(session_id)
    if not target_session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if _terminal(lifecycle_status=target_session.lifecycle_status, closed_at=target_session.closed_at):
        raise HTTPException(status_code=409, detail=f"Session {session_id} is closed")
    return target_session


async def _handle_close_link_request(
    *,
    session_id: str,
    request: SendMessageRequest,
    identity: CallerIdentity,
) -> SendMessageResponseDTO:
    """Handle close-link requests, optionally delivering a final message first."""
    if not identity.session_id:
        raise HTTPException(status_code=400, detail="close_link requires caller session identity")

    active_link = await resolve_link_for_sender_target(
        sender_session_id=identity.session_id,
        target_session_id=session_id,
    )
    if not active_link:
        return SendMessageResponseDTO(status="error", message="no active direct link found")

    if request.message:
        await _process_api_message(session_id, request.message, _build_metadata())

    closed_link_id = await close_link_for_member(
        caller_session_id=identity.session_id,
        target_session_id=session_id,
    )
    return SendMessageResponseDTO(
        status="success",
        mode="direct",
        action="closed",
        link_id=closed_link_id,
    )


@dataclass(frozen=True)
class DirectMessageContext:
    """Resolved caller/target metadata for direct conversations."""

    caller_label: str
    target_label: str
    caller_computer: str
    target_computer: str


async def _build_direct_message_context(
    caller_session_id: str,
    target_session_id: str,
    target_session: Session | None,
) -> DirectMessageContext:
    """Load caller/target display context for direct messaging."""
    caller_session = await db.get_session(caller_session_id)
    resolved_target_session = target_session or await db.get_session(target_session_id)
    return DirectMessageContext(
        caller_label=caller_session.title if caller_session and caller_session.title else caller_session_id,
        target_label=(
            resolved_target_session.title
            if resolved_target_session and resolved_target_session.title
            else target_session_id
        ),
        caller_computer=caller_session.computer_name if caller_session else config.computer.name,
        target_computer=resolved_target_session.computer_name if resolved_target_session else config.computer.name,
    )


async def _create_direct_link(
    caller_session_id: str,
    target_session_id: str,
    context: DirectMessageContext,
) -> tuple[str, int] | SendMessageResponseDTO:
    """Create or resolve the active direct link for this caller/target pair."""
    link_ctx = await resolve_link_for_sender_target(
        sender_session_id=caller_session_id,
        target_session_id=target_session_id,
    )
    if link_ctx:
        return _active_direct_link_response(link_ctx[0].link_id, already_active=True)

    link, _ = await create_or_reuse_direct_link(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        caller_name=context.caller_label,
        target_name=context.target_label,
        caller_computer=context.caller_computer,
        target_computer=context.target_computer,
    )
    resolved_link_ctx = await resolve_link_for_sender_target(
        sender_session_id=caller_session_id,
        target_session_id=target_session_id,
    )
    if not resolved_link_ctx:
        raise HTTPException(status_code=500, detail="failed to resolve direct link")
    return link.link_id, len(resolved_link_ctx[1])


async def _deliver_direct_message(
    *,
    link_id: str,
    caller_session_id: str,
    session_id: str,
    message_text: str,
    metadata: MessageMetadata,
) -> int:
    """Deliver a direct-conversation message to active peers."""
    peers = await get_peer_members(link_id=link_id, sender_session_id=caller_session_id)
    delivery_targets = [peer.session_id for peer in peers] or [session_id]
    delivered_to = 0
    for target_id in delivery_targets:
        target_for_delivery = await db.get_session(target_id)
        if not target_for_delivery:
            logger.info("Skipping direct delivery to missing session %s", target_id)
            continue
        if _terminal(lifecycle_status=target_for_delivery.lifecycle_status, closed_at=target_for_delivery.closed_at):
            logger.info("Skipping direct delivery to closed session %s", target_id)
            continue
        await _process_api_message(target_id, message_text, metadata)
        delivered_to += 1
    return delivered_to


async def _handle_direct_message_request(
    *,
    session_id: str,
    request: SendMessageRequest,
    identity: CallerIdentity,
    target_session: Session | None,
    metadata: MessageMetadata,
) -> SendMessageResponseDTO:
    """Create or reuse a direct link and deliver the message to active peers."""
    if not identity.session_id:
        raise HTTPException(status_code=400, detail="direct mode requires caller session identity")

    context = await _build_direct_message_context(identity.session_id, session_id, target_session)
    link_result = await _create_direct_link(
        caller_session_id=identity.session_id,
        target_session_id=session_id,
        context=context,
    )
    if isinstance(link_result, SendMessageResponseDTO):
        return link_result

    link_id, member_count = link_result
    message_text = _format_direct_conversation_intro(
        caller_session_id=identity.session_id,
        caller_computer=context.caller_computer,
        message_text=request.message or "",
    )
    delivered_to = await _deliver_direct_message(
        link_id=link_id,
        caller_session_id=identity.session_id,
        session_id=session_id,
        message_text=message_text,
        metadata=metadata,
    )

    if delivered_to == 0:
        return SendMessageResponseDTO(
            status="error",
            mode="direct",
            link_id=link_id,
            message="No active target sessions available for delivery",
        )

    return SendMessageResponseDTO(
        status="success",
        mode="direct",
        link_id=link_id,
        link_state="created",
        delivered_to=delivered_to,
        members=member_count,
    )


async def _reject_existing_direct_link(
    session_id: str,
    identity: CallerIdentity,
) -> SendMessageResponseDTO | None:
    """Return the standard error response if a work send conflicts with a direct link."""
    if not identity.session_id:
        return None

    existing_link = await resolve_link_for_sender_target(
        sender_session_id=identity.session_id,
        target_session_id=session_id,
    )
    if not existing_link:
        return None
    return _active_direct_link_response(existing_link[0].link_id, already_active=False)


@router.post("/sessions/{session_id}/message", response_model_exclude_none=True)
async def send_message_endpoint(
    http_request: Request,
    session_id: str,
    request: SendMessageRequest,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(clearance_sessions_send),
) -> SendMessageResponseDTO:
    """Send message to session."""
    await check_session_access(http_request, session_id)
    try:
        target_session = None
        if not is_remote_target(computer, config.computer.name):
            target_session = await _load_target_session_for_message(session_id, request.message)

        if request.close_link:
            return await _handle_close_link_request(
                session_id=session_id,
                request=request,
                identity=identity,
            )

        if not request.message:
            raise HTTPException(status_code=400, detail="message required")

        metadata = _build_metadata()
        if request.direct:
            return await _handle_direct_message_request(
                session_id=session_id,
                request=request,
                identity=identity,
                target_session=target_session,
                metadata=metadata,
            )

        existing_link_response = await _reject_existing_direct_link(session_id, identity)
        if existing_link_response:
            return existing_link_response

        # Auto-register a one-shot listener so the caller receives the response.
        if identity.session_id and identity.session_id != session_id and identity.tmux_session_name:
            try:
                await register_listener(
                    target_session_id=session_id,
                    caller_session_id=identity.session_id,
                    caller_tmux_session=identity.tmux_session_name,
                    one_shot=True,
                )
            except Exception:
                logger.debug(
                    "One-shot listener registration failed: caller=%s target=%s", identity.session_id, session_id
                )

        message_text = await _wrap_message_with_origin(request.message, identity.session_id)
        await _process_api_message(session_id, message_text, metadata, computer=computer)
        return SendMessageResponseDTO(status="success", mode="work")
    except (SessionMessageRejectedError, UnidentifiableCallerError) as exc:
        if isinstance(exc, UnidentifiableCallerError):
            logger.warning("Refused unidentifiable caller: caller=%s target=%s", exc.caller_session_id, session_id)
        raise HTTPException(status_code=exc.http_status_code, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_message failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e
