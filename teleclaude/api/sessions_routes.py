"""Session management endpoints (list, create, delete, send-message)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.agent_dispatch_errors import (
    agent_dispatch_http_refusal,
    emit_run_outcome,
    present_routing_explanation,
    read_routing_reason,
    run_dispatch_refusal_reason,
    run_refusal_outcome,
)
from teleclaude.api.auth import (
    CallerIdentity,
    clearance_sessions_end,
    clearance_sessions_list,
    clearance_sessions_send,
    clearance_sessions_start,
)
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api.run_session_shapes import infer_role_and_slug_from_message
from teleclaude.api.session_access import check_session_access
from teleclaude.api.session_create_launch import (
    ScheduledLaunch,
    build_launch_intent,
    resolve_enabled_agent,
    resolve_scheduled_launch,
    scheduled_create_request,
)
from teleclaude.api.session_direct_messages import (
    _build_direct_message_context,
    _create_direct_link,
    _deliver_direct_message,
    _direct_conversation_intro_body,
    _format_direct_conversation_intro,
    _reject_existing_direct_link,
)
from teleclaude.api.session_ownership import RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_reminder_summary import attach_next_reminders, observe_session_reminder_summaries
from teleclaude.api.session_remote import is_remote_create_target, is_remote_target
from teleclaude.api.session_route_helpers import build_metadata as _build_metadata
from teleclaude.api.session_route_helpers import close_accepted as _close_accepted
from teleclaude.api.session_route_helpers import resolve_created_session_transport as _resolve_created_session_transport
from teleclaude.api.session_view_models import enrich_human_names, filter_sessions_by_role
from teleclaude.api.sessions_actions_routes import guard_generic_create_session
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    ScheduledSessionRequest,
    SendMessageRequest,
    SendMessageResponseDTO,
    SessionDTO,
)
from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core import command_handlers
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.conversation_messages import (
    MACHINE_ROLE_LABELS as _MACHINE_ROLE_LABELS,
)
from teleclaude.core.conversation_messages import (
    format_identity_conversation,
    format_identity_header,
    is_conversation_bridge_message,
    is_orchestrator_dispatch_message,
    resolve_session_event_author,
)
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError, UnidentifiableCallerError
from teleclaude.core.injected_text import MachineRoleLabel
from teleclaude.core.models import (
    AgentDispatchMode,
    MessageAuthor,
    MessageMetadata,
    SessionEntryPoint,
    SessionLaunchIntent,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata, WebOriginMetadata
from teleclaude.core.next_machine.session_hold import hold_todo_for_manual_session_close
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    close_link_for_member,
    create_or_reuse_direct_link,
    register_listener,
    resolve_link_for_sender_target,
)
from teleclaude.core.session_status import is_session_terminal as _terminal

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import Session
    from teleclaude.core.reminders import ReminderService
from teleclaude.types.commands import OCCURRENCE_KEY, CloseSessionCommand, CreateSessionCommand

logger = get_logger(__name__)

_UNIDENTIFIABLE_CALLER_EVENT = "unidentifiable_caller_refused"
_SESSION_START_IGNITION_PATH = "session_start"
_DIRECT_IGNITION_EXISTING_SESSION_PATH = "existing_session"
_DIRECT_IGNITION_SESSION_CREATE_PATH = "session_create"
_EMPTY_MESSAGE_TEXT = ""


@dataclass(frozen=True)
class ResolvedSessionEventIdentity:
    author: MessageAuthor
    job_role: str | None
    header: str


_CONFIG_UNSET = object()

_STATE = SimpleNamespace(client=None, cache=None, reminder_service=None)
_SESSION_EVENT_IDENTITY_RESOLVED_EVENT = "session_event_identity_resolved"

router = APIRouter()


def configure(
    client: AdapterClient | None | object = _CONFIG_UNSET,
    cache: DaemonCache | None | object = _CONFIG_UNSET,
    reminder_service: ReminderService | None | object = _CONFIG_UNSET,
) -> None:
    if client is not _CONFIG_UNSET:
        _STATE.client = client
    if cache is not _CONFIG_UNSET:
        _STATE.cache = cache
    if reminder_service is not _CONFIG_UNSET:
        _STATE.reminder_service = reminder_service


def _check_remote_session_owner(request: Request, ownership: RemoteOwnership) -> None:
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")

    if not email:
        return
    if role == HUMAN_ROLE_ADMIN:
        return
    if ownership.snapshot.human_email == email:
        return

    raise HTTPException(status_code=403, detail="Forbidden: not session owner")


def _extract_initiator_session_id(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> str | None:
    if request.direct and not identity.session_id:
        raise HTTPException(
            status_code=400,
            detail="direct mode requires caller session identity",
        )

    if identity.session_id and not identity.session_id.startswith("web:"):
        return identity.session_id
    return None


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
) -> str:
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

    link, _ = await create_or_reuse_direct_link(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        caller_name=caller_label,
        target_name=target_label,
        caller_computer=caller_computer,
        target_computer=target_computer,
    )
    return link.link_id


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
    return ListSessionsQuery(
        computer=computer,
        include_closed=include_closed,
        all_sessions=all_sessions,
        job=job,
    )


async def _prepare_create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity,
    scheduled_launch: ScheduledLaunch | None = None,
) -> tuple[MessageMetadata, str | None, str | None, SessionLaunchIntent | None, Session | None]:
    """Prepare session creation metadata, initiator ID, and launch intent."""
    initiator_session_id = _extract_initiator_session_id(request, identity)

    origin, caller_email, origin_meta = _resolve_origin(request, identity)
    effective_human_role = _resolve_effective_human_role(request.human_role, identity.human_role)

    inferred_role, inferred_job, _ = infer_role_and_slug_from_message(request.message)
    req_system_role = scheduled_launch.system_role if scheduled_launch else inferred_role
    req_job = scheduled_launch.job if scheduled_launch else inferred_job

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

    initial_input = None if request.direct and identity.session_id else request.message

    effective_thinking_mode = request.thinking_mode or "slow"
    validated_request_agent = resolve_enabled_agent(request.agent) if request.agent else None
    launch_intent, direct_caller_session = await build_launch_intent(
        request,
        identity,
        validated_request_agent,
        effective_thinking_mode,
        scheduled_launch,
    )
    metadata.launch_intent = launch_intent
    return metadata, initiator_session_id, initial_input, launch_intent, direct_caller_session


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
        merged = filter_sessions_by_role(request, merged)

        # Job filter: narrows existing visibility results
        if query.job:
            merged = [s for s in merged if s.job == query.job]

        dtos = [SessionDTO.from_core(s, computer=s.computer) for s in merged]
        dtos = await attach_next_reminders(
            dtos,
            {session.session_id for session in local_sessions},
            _STATE.reminder_service,
        )
        observe_session_reminder_summaries(dtos)
        return enrich_human_names(dtos)
    except Exception as e:
        logger.error("list_sessions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e


async def _create_session_response(
    request: CreateSessionRequest,
    identity: CallerIdentity,
    *,
    scheduled_launch: ScheduledLaunch | None = None,
) -> CreateSessionResponseDTO:
    """Create a session after the caller path has established routing authority."""
    logger.info(
        "create_session request: computer=%s project=%s agent=%s thinking_mode=%s launch_kind=%s native_session_id=%s",
        request.computer,
        request.project_path,
        request.agent,
        request.thinking_mode,
        request.launch_kind,
        request.native_session_id,
    )

    try:
        (
            metadata,
            initiator_session_id,
            initial_input,
            _launch_intent,
            direct_caller_session,
        ) = await _prepare_create_session(request, identity, scheduled_launch)
    except UnidentifiableCallerError as exc:
        logger.warning(
            _UNIDENTIFIABLE_CALLER_EVENT,
            caller_session_id=exc.caller_session_id,
            ignition_path=_SESSION_START_IGNITION_PATH,
        )
        raise HTTPException(status_code=exc.http_status_code, detail=str(exc)) from exc

    cmd = CommandMapper.map_api_input(
        "new_session",
        {
            "skip_listener_registration": request.skip_listener_registration,
            "initiator_session_id": initiator_session_id,
            "initial_input": initial_input,
            "title": request.title,
            "working_slug": infer_role_and_slug_from_message(request.message)[2],
        },
        metadata,
        computer=request.computer,
    )

    launch_mode = (
        cmd.launch_intent.dispatch_mode
        if isinstance(cmd, CreateSessionCommand) and cmd.launch_intent and cmd.launch_intent.dispatch_mode
        else AgentDispatchMode.AUTOMATIC
    )
    command_entry_point = scheduled_launch.entry_point if scheduled_launch else SessionEntryPoint.API_CREATE
    try:
        guard_result = await guard_generic_create_session(request, cmd, identity)
    except RunSessionRefusal as exc:
        emit_run_outcome(
            selected_agent=None,
            request_id=cmd.request_id,
            entry_point=command_entry_point,
            dispatch_mode=launch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
        )
        raise
    if isinstance(cmd, CreateSessionCommand):
        cmd.entry_point = command_entry_point
        if cmd.launch_intent is not None:
            cmd.launch_intent.entry_point = cmd.entry_point
        if scheduled_launch is None and cmd.job == "reviewer" and initiator_session_id:
            producer = await db.get_session(initiator_session_id)
            cmd.producer_agent = producer.active_agent if producer is not None else None
    try:
        result = await dispatch_command(_STATE.client, cmd)
        if not isinstance(result, dict):
            raise HTTPException(status_code=500, detail="Failed to create session")
        data = result
        session_id, tmux_session_name = await _resolve_created_session_transport(data)

        remote_create = is_remote_create_target(request.computer, config.computer.name)
        if request.direct and identity.session_id and not remote_create:
            link_id = await _link_direct_sessions(
                caller_session_id=identity.session_id,
                target_session_id=session_id,
                caller_session=direct_caller_session,
            )
            caller_resolution = await _resolve_caller_event_author(identity.session_id)
            if caller_resolution is None:
                raise UnidentifiableCallerError(caller_session_id=identity.session_id)
            caller_author, caller_job_role = caller_resolution
            occurred_at = datetime.now(UTC)
            message_body = _direct_conversation_intro_body(request.message or _EMPTY_MESSAGE_TEXT)
            delivered_to = await _deliver_direct_message(
                client=_STATE.client,
                link_id=link_id,
                caller_session_id=identity.session_id,
                session_id=session_id,
                message_text=_format_direct_conversation_intro(
                    author=caller_author,
                    occurred_at=occurred_at,
                    message_text=request.message or _EMPTY_MESSAGE_TEXT,
                ),
                message_body=message_body,
                metadata=metadata,
                caller_author=caller_author,
                caller_job_role=caller_job_role,
                occurred_at=occurred_at,
                ignition_path=_DIRECT_IGNITION_SESSION_CREATE_PATH,
            )
            if delivered_to == 0:
                raise HTTPException(status_code=409, detail="No active target sessions available for direct ignition")

        routing_explanation = present_routing_explanation(
            data,
            human_facing=not identity.system_role and bool(identity.email),
            request_id=cmd.request_id,
            session_id=session_id,
            entry_point=cmd.entry_point
            if isinstance(cmd, CreateSessionCommand) and cmd.entry_point
            else SessionEntryPoint.API_CREATE,
        )
        emit_run_outcome(
            selected_agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
            request_id=cmd.request_id,
            session_id=session_id,
            entry_point=command_entry_point,
            dispatch_mode=launch_mode,
            reason=AgentDispatchReason.HELD_WITHOUT_DRIVER if guard_result.held_without_driver else None,
        )
        return CreateSessionResponseDTO(
            status="success",
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            computer=request.computer if remote_create else None,
            agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
            routing_explanation=routing_explanation,
            routing_reason=read_routing_reason(data),
        )
    except HTTPException as exc:
        raise exc
    except Exception as e:
        refusal = agent_dispatch_http_refusal(e)
        if refusal:
            reason = run_dispatch_refusal_reason(e)
            if reason is not None:
                emit_run_outcome(
                    selected_agent=None,
                    request_id=cmd.request_id,
                    entry_point=command_entry_point,
                    dispatch_mode=launch_mode,
                    outcome=run_refusal_outcome(reason),
                    reason=reason,
                )
            raise refusal from e
        logger.error("create_session failed (computer=%s): %s", request.computer, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}") from e


@router.post("/sessions", response_model_exclude_none=True)
async def create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity = Depends(clearance_sessions_start),
) -> CreateSessionResponseDTO:
    """Create a generic session with only automatic or manual-preference intent."""
    return await _create_session_response(request, identity)


@router.post("/internal/cron/sessions", response_model_exclude_none=True)
async def create_scheduled_session(
    request: ScheduledSessionRequest,
    identity: CallerIdentity = Depends(clearance_sessions_start),
) -> CreateSessionResponseDTO:
    """Create a scheduled session from daemon-loaded job configuration only."""
    scheduled_launch = resolve_scheduled_launch(request)
    return await _create_session_response(
        scheduled_create_request(request, scheduled_launch), identity, scheduled_launch=scheduled_launch
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=202,
    responses={200: {"description": "Session already closed"}},
)
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
        session = await db.get_session(session_id)
        if session and (session.closed_at or session.lifecycle_status == "closed"):
            response = JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": f"Session {session_id} already closed",
                },
            )
            return response  # type: ignore[return-value]  # pyright: ignore[reportReturnType]

        cmd = CloseSessionCommand(session_id=session_id)
        await dispatch_command(_STATE.client, cmd)

        return _close_accepted(cmd)  # type: ignore[return-value]  # pyright: ignore[reportReturnType]
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.error("Failed to end session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e


async def _resolve_caller_event_identity(
    caller_session_id: str | None,
) -> ResolvedSessionEventIdentity | None:
    if not caller_session_id:
        return None
    ownership = await resolve_session_ownership(caller_session_id, db=db, cache=_STATE.cache)
    if ownership is None:
        raise UnidentifiableCallerError(caller_session_id=caller_session_id)
    if isinstance(ownership, RemoteOwnership):
        role = ownership.snapshot.system_role
        agent = ownership.snapshot.active_agent
        thinking_mode = ownership.snapshot.thinking_mode
        job_role = ownership.snapshot.job
        computer = ownership.computer
    else:
        caller = ownership.session
        role = caller.system_role
        agent = caller.active_agent
        thinking_mode = caller.thinking_mode
        job_role = caller.job
        computer = caller.computer_name
    role_label = _MACHINE_ROLE_LABELS.get((role or "").strip())
    author = resolve_session_event_author(
        session_id=caller_session_id,
        system_role=role,
        active_agent=agent,
        thinking_mode=thinking_mode,
    )
    category_parts = [part for part in (agent.title() if agent else None, job_role) if part]
    header = format_identity_header(
        role=MachineRoleLabel.AGENT if agent else role_label or MachineRoleLabel.AGENT,
        category=" · ".join(category_parts) or None,
        session_id=caller_session_id,
        computer=computer or config.computer.name,
    )
    logger.info(
        _SESSION_EVENT_IDENTITY_RESOLVED_EVENT,
        source_session_id=caller_session_id,
        author_kind=author.kind.value,
        agent_runtime=author.agent_runtime,
        job_role=job_role,
        machine_role=author.machine_role,
    )
    return ResolvedSessionEventIdentity(author=author, job_role=job_role, header=header)


async def _resolve_caller_event_author(caller_session_id: str | None) -> tuple[MessageAuthor, str | None] | None:
    identity = await _resolve_caller_event_identity(caller_session_id)
    return (identity.author, identity.job_role) if identity is not None else None


async def _wrap_message_with_origin(
    message_text: str,
    caller_session_id: str | None,
    event_identity: ResolvedSessionEventIdentity | None = None,
) -> tuple[str, int, int]:
    if is_conversation_bridge_message(message_text) or is_orchestrator_dispatch_message(message_text):
        return message_text, 0, 0
    identity = event_identity or await _resolve_caller_event_identity(caller_session_id)
    header = identity.header if identity is not None else None
    if not header:
        return message_text, 0, 0
    return format_identity_conversation(header=header, body=message_text)


async def _process_api_message(
    session_id: str,
    message_text: str,
    metadata: MessageMetadata,
    computer: str | None = None,
) -> None:
    # guard: loose-dict - CommandMapper.map_api_input payload boundary
    payload: dict[str, object] = {"session_id": session_id, "text": message_text}
    if metadata.caller_session_id:
        payload[OCCURRENCE_KEY] = uuid4().hex  # identity-content needs a durable receipt key (f52119d34)
    cmd = CommandMapper.map_api_input("message", payload, metadata, computer=computer)
    await dispatch_command(_STATE.client, cmd)


async def _load_target_session_for_message(
    session_id: str,
    message_text: str | None,
) -> Session | None:
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


async def _handle_direct_message_request(
    *,
    session_id: str,
    request: SendMessageRequest,
    identity: CallerIdentity,
    target_session: Session | None,
    metadata: MessageMetadata,
) -> SendMessageResponseDTO:
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
    caller_resolution = await _resolve_caller_event_author(identity.session_id)
    if caller_resolution is None:
        raise UnidentifiableCallerError(caller_session_id=identity.session_id)
    caller_author, caller_job_role = caller_resolution
    message_body = _direct_conversation_intro_body(request.message or _EMPTY_MESSAGE_TEXT)
    occurred_at = datetime.now(UTC)
    message_text = _format_direct_conversation_intro(
        author=caller_author,
        occurred_at=occurred_at,
        message_text=request.message or _EMPTY_MESSAGE_TEXT,
    )
    delivered_to = await _deliver_direct_message(
        client=_STATE.client,
        link_id=link_id,
        caller_session_id=identity.session_id,
        session_id=session_id,
        message_text=message_text,
        message_body=message_body,
        metadata=metadata,
        caller_author=caller_author,
        caller_job_role=caller_job_role,
        occurred_at=occurred_at,
        ignition_path=_DIRECT_IGNITION_EXISTING_SESSION_PATH,
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


@router.post("/sessions/{session_id}/message", response_model_exclude_none=True)
async def send_message_endpoint(
    http_request: Request,
    session_id: str,
    request: SendMessageRequest,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(clearance_sessions_send),
) -> SendMessageResponseDTO:
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

        event_identity = await _resolve_caller_event_identity(identity.session_id)
        caller_resolution = (event_identity.author, event_identity.job_role) if event_identity is not None else None
        if caller_resolution is not None:
            caller_author, caller_job_role = caller_resolution
            metadata.caller_session_id = identity.session_id
            metadata.caller_author_kind = caller_author.kind.value
            metadata.caller_author_display = caller_author.display
            metadata.caller_agent_runtime = caller_author.agent_runtime
            metadata.caller_thinking_mode = caller_author.thinking_mode
            metadata.caller_machine_role = caller_author.machine_role
            metadata.caller_job_role = caller_job_role
        message_text, caller_prefix_len, caller_suffix_len = await _wrap_message_with_origin(
            request.message,
            identity.session_id,
            event_identity,
        )
        if caller_resolution is not None:
            metadata.caller_origin_prefix_len = caller_prefix_len
            metadata.caller_origin_suffix_len = caller_suffix_len
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
