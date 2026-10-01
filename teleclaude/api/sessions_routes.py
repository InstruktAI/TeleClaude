"""Session management endpoints (list, create, delete, send-message)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
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
    caller_for_role_resolution,
    carried_caller,
    principal_for_carried_caller,
    resolve_caller_provenance,
)
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api.run_session_shapes import infer_command_from_message, infer_role_and_slug_from_message
from teleclaude.api.session_authority import ACT_END, ACT_SEND_MESSAGE, refuse_act_on_ancestor
from teleclaude.api.session_create_launch import (
    build_launch_intent,
    resolve_enabled_agent,
)
from teleclaude.api.session_direct_messages import (
    _build_direct_message_context,
    _create_direct_link,
    _deliver_direct_message,
    _format_direct_conversation_intro,
    _reject_existing_direct_link,
)
from teleclaude.api.session_ownership import RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_reminder_summary import attach_next_reminders, observe_session_reminder_summaries
from teleclaude.api.session_remote import is_remote_create_target, is_remote_target
from teleclaude.api.session_route_helpers import build_metadata as _build_metadata
from teleclaude.api.session_route_helpers import close_accepted as _close_accepted
from teleclaude.api.session_route_helpers import dispatch_caller_command, http_exception_for_relay_failure
from teleclaude.api.session_route_helpers import resolve_created_session_transport as _resolve_created_session_transport
from teleclaude.api.session_view_models import enrich_human_names
from teleclaude.api.sessions_actions_routes import guard_generic_create_session
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    SendMessageRequest,
    SendMessageResponseDTO,
    SessionDTO,
)
from teleclaude.caller_identity import RoleResolver
from teleclaude.config import config
from teleclaude.constants import SlashCommand
from teleclaude.core import command_handlers
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.command_dispatch import RelayFailure, relay_caller_read
from teleclaude.core.command_input import (
    WORKTREE_BOUND_WORKER_COMMANDS,
    CommandInputMode,
    RefusedCommandInput,
    ResolvedCommandInput,
    infer_command_input_metadata,
)
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.conversation_messages import (
    MACHINE_ROLE_LABELS as _MACHINE_ROLE_LABELS,
)
from teleclaude.core.conversation_messages import (
    format_identity_conversation,
    format_identity_header,
    resolve_session_event_author,
)
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import (
    DirectLinkExclusivityError,
    SessionMessageRejectedError,
    UnidentifiableCallerError,
)
from teleclaude.core.injected_text import MachineRoleLabel
from teleclaude.core.models import (
    AgentDispatchMode,
    JsonDict,
    MessageAuthor,
    MessageMetadata,
    SessionEntryPoint,
    SessionLaunchIntent,
    parse_peer_session_snapshots,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.core.next_machine.session_hold import hold_todo_for_manual_session_close
from teleclaude.core.operations.service import SerializedOperation, get_operations_service
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_links import (
    active_direct_peer,
    close_link_for_member,
    create_or_reuse_direct_link,
    resolve_link_for_sender_target,
)
from teleclaude.core.session_listeners import (
    register_listener,
)
from teleclaude.core.session_listing import sessions_reached_by
from teleclaude.core.session_startup_message import resolve_command_input
from teleclaude.core.session_status import is_session_terminal as _terminal
from teleclaude.core.session_utils import resolve_working_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import Session
    from teleclaude.core.reminders import ReminderService
from teleclaude.types.commands import OCCURRENCE_KEY, CloseSessionCommand, CreateSessionCommand

logger = get_logger(__name__)


_UNIDENTIFIABLE_CALLER_EVENT = "unidentifiable_caller_refused"
_SESSION_START_IGNITION_PATH = "session_start"
# Refusal detail for a session-start ignition whose caller is already in a
# direct conversation; refused before the session is created so no unlinked
# session is left behind.
_EXCLUSIVE_DIRECT_LINK_DETAIL = (
    "Caller is already in a direct conversation with {peer_label} ({peer_session_id}). "
    "Direct conversation is exclusive to two peers; close it before starting another."
)
_EMPTY_MESSAGE_TEXT = ""
_WORKTREE_SUBDIR_TEMPLATE = "trees/{slug}"
_WORKTREE_DIRECTORY_MISSING_TEMPLATE = "required worktree directory does not exist: {worktree_dir}"


@dataclass(frozen=True)
class ResolvedSessionEventIdentity:
    author: MessageAuthor
    job_role: str | None
    header: str


_CONFIG_UNSET = object()
_LIST_SESSIONS_READ = "list_sessions"
_INCLUDE_CLOSED_FIELD = "include_closed"
_NO_REMOTE_COMPUTER = ""
_REMOTE_SESSION_LISTING_UNAVAILABLE_DETAIL = "Remote session listing is unavailable"
_REMOTE_SESSION_LISTING_INVALID_DETAIL = "Remote session listing returned invalid data"
_REMOTE_SESSION_LISTING_FAILURE_EVENT = "list_sessions.remote_failure"

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


def _extract_initiator_session_id(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> str | None:
    if request.direct and not identity.session_id:
        raise HTTPException(
            status_code=400,
            detail="direct mode requires caller session identity",
        )

    if identity.session_id:
        return identity.session_id
    return None


def _resolve_origin(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> tuple[str, str | None, Mapping[str, object] | None]:
    """Resolve origin, caller_email, and origin_metadata from request and identity.

    Daemon-internal callers (e.g. WhatsApp handler) may supply origin via top-level
    request fields or nested inside the metadata dict.  When neither is present,
    origin defaults to terminal.

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
    typed_origin: TerminalOriginMetadata | None = None
    if caller_email:
        typed_origin = TerminalOriginMetadata(email=caller_email)
    return origin, caller_email, typed_origin


async def _link_direct_sessions(
    *,
    caller_session_id: str,
    target_session_id: str,
    caller_session: Session | None,
) -> str:
    """Create the direct link between caller and target sessions after creation.

    Does not touch listener records — the two subscription axes are orthogonal.
    Notification suppression while the link is active is enforced at delivery
    time in `_notify_listeners`. See `local/projects/teleclaude/spec/session-subscriptions`.
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
) -> tuple[MessageMetadata, str | None, str | None, SessionLaunchIntent | None, Session | None]:
    """Prepare session creation metadata, initiator ID, and launch intent."""
    initiator_session_id = _extract_initiator_session_id(request, identity)

    origin, caller_email, origin_meta = _resolve_origin(request, identity)

    inferred_role, inferred_job, _ = infer_role_and_slug_from_message(request.message)
    req_system_role = inferred_role
    req_job = inferred_job

    metadata = _build_metadata(
        origin=origin,
        project_path=request.project_path,
        subdir=request.subdir,
        human_email=caller_email,
        human_role=None,
        origin_metadata=origin_meta,
        system_role=req_system_role,
        job=req_job,
        company=request.company,
    )

    initial_input = None if request.direct and identity.session_id else request.message

    effective_thinking_mode = request.thinking_mode or "slow"
    validated_request_agent = resolve_enabled_agent(request.agent) if request.agent else None
    launch_intent, direct_caller_session = await build_launch_intent(
        request,
        identity,
        validated_request_agent,
        effective_thinking_mode,
    )
    metadata.launch_intent = launch_intent
    return metadata, initiator_session_id, initial_input, launch_intent, direct_caller_session


def _prepare_interactive_create_request(request: CreateSessionRequest) -> CreateSessionRequest:
    """Resolve local TUI command input before generic-create metadata and guards."""
    result = resolve_command_input(request.message, request.command_input_mode)
    if isinstance(result, RefusedCommandInput):
        raise RunSessionRefusal(
            status_code=400,
            detail=result.detail,
            reason=AgentDispatchReason.COMMAND_INVALID,
        )
    if not isinstance(result, ResolvedCommandInput):
        return request
    metadata = infer_command_input_metadata(result.command, result.args)
    normalized_request = request.model_copy(
        update={"message": result.normalized_message, "command_input_source_text": request.message}
    )
    try:
        slash_command = SlashCommand(result.command)
    except ValueError:
        slash_command = None
    if slash_command in WORKTREE_BOUND_WORKER_COMMANDS and metadata.working_slug:
        subdir = _WORKTREE_SUBDIR_TEMPLATE.format(slug=metadata.working_slug)
        worktree_dir = Path(resolve_working_dir(normalized_request.project_path, subdir))
        if not worktree_dir.is_dir():
            raise RunSessionRefusal(
                status_code=400,
                detail=_WORKTREE_DIRECTORY_MISSING_TEMPLATE.format(worktree_dir=worktree_dir),
                reason=AgentDispatchReason.WORKTREE_MISMATCH,
            )
        normalized_request = normalized_request.model_copy(update={"subdir": subdir})
    return normalized_request


@router.get("/sessions")
async def list_sessions(
    request: Request,
    query: ListSessionsQuery = Depends(_parse_list_sessions_query),
    _identity: CallerIdentity = Depends(carried_caller),
) -> list[SessionDTO]:
    """List sessions from local storage and remote cache.

    Args:
        request: FastAPI request
        computer: Optional filter by computer name
        include_closed: Include closed sessions

    Returns:
        List of session summaries (merged local + cached remote)
    """
    try:
        if is_remote_target(query.computer, config.computer.name):
            if _STATE.client is None:
                raise HTTPException(status_code=503, detail=_REMOTE_SESSION_LISTING_UNAVAILABLE_DETAIL)
            principal = principal_for_carried_caller(_identity, required=True)
            target_computer = query.computer or _NO_REMOTE_COMPUTER
            request_data: JsonDict = {_INCLUDE_CLOSED_FIELD: query.include_closed}
            try:
                remote_data = await relay_caller_read(
                    _STATE.client,
                    target_computer,
                    _LIST_SESSIONS_READ,
                    principal=principal,
                    request=request_data,
                )
            except RelayFailure as exc:
                logger.error(_REMOTE_SESSION_LISTING_FAILURE_EVENT, computer=target_computer, exc_info=True)
                raise http_exception_for_relay_failure(exc) from exc
            if not isinstance(remote_data, list):
                raise HTTPException(status_code=502, detail=_REMOTE_SESSION_LISTING_INVALID_DETAIL)
            if any(not isinstance(item, dict) for item in remote_data):
                raise HTTPException(status_code=502, detail=_REMOTE_SESSION_LISTING_INVALID_DETAIL)
            peer_data = cast(list[JsonDict], remote_data)
            remote_sessions = parse_peer_session_snapshots(peer_data, target_computer)
            if len(remote_sessions) != len(peer_data):
                raise HTTPException(status_code=502, detail=_REMOTE_SESSION_LISTING_INVALID_DETAIL)
            for session in remote_sessions:
                session.computer = target_computer
            caller_session_id = request.headers.get("x-caller-session-id")
            if caller_session_id and not query.all_sessions:
                remote_sessions = [
                    session for session in remote_sessions if session.initiator_session_id == caller_session_id
                ]
            if query.job:
                remote_sessions = [session for session in remote_sessions if session.job == query.job]
            dtos = [SessionDTO.from_core(session, computer=session.computer) for session in remote_sessions]
            observe_session_reminder_summaries(dtos)
            return enrich_human_names(dtos)

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
        merged = sessions_reached_by(
            caller_for_role_resolution(_identity),
            merged,
            resolver=RoleResolver(),
            caller_session=caller_session_id,
        )
        if caller_session_id and not query.all_sessions:
            merged = [s for s in merged if s.initiator_session_id == caller_session_id]

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error("list_sessions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}") from e


async def _create_session_response(
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> CreateSessionResponseDTO:
    """Create a session after the caller path has established routing authority."""
    if request.command_input_mode is CommandInputMode.INTERACTIVE_SHORTHAND and not is_remote_create_target(
        request.computer, config.computer.name
    ):
        request = _prepare_interactive_create_request(request)

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
        ) = await _prepare_create_session(request, identity)
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
            "command": infer_command_from_message(request.message),
            "working_slug": infer_role_and_slug_from_message(request.message)[2],
            "command_input_mode": request.command_input_mode,
            "command_input_source_text": request.command_input_source_text,
        },
        metadata,
        computer=request.computer,
    )

    launch_mode = (
        cmd.launch_intent.dispatch_mode
        if isinstance(cmd, CreateSessionCommand) and cmd.launch_intent and cmd.launch_intent.dispatch_mode
        else AgentDispatchMode.AUTOMATIC
    )
    command_entry_point = SessionEntryPoint.API_CREATE
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
    # Fail fast before a session is spawned. The authoritative check runs under
    # the endpoint locks inside link creation; this only spares the caller a
    # session it could not have linked.
    if request.direct and identity.session_id:
        blocking_peer = await active_direct_peer(identity.session_id)
        if blocking_peer is not None:
            raise HTTPException(
                status_code=409,
                detail=_EXCLUSIVE_DIRECT_LINK_DETAIL.format(
                    peer_label=blocking_peer.participant_name or blocking_peer.session_id,
                    peer_session_id=blocking_peer.session_id,
                ),
            )
    try:
        result = await dispatch_caller_command(_STATE.client, cmd, identity)
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
                metadata=metadata,
                caller_author=caller_author,
                caller_job_role=caller_job_role,
                occurred_at=occurred_at,
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
    except DirectLinkExclusivityError as exc:
        # Lost the race against a concurrent ignition on this caller: the
        # session exists but stays unlinked rather than becoming a third peer.
        raise HTTPException(status_code=exc.http_status_code, detail=str(exc)) from exc
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
    identity: CallerIdentity = Depends(carried_caller),
) -> CreateSessionResponseDTO:
    """Create a generic session with only automatic or manual-preference intent."""
    return await _create_session_response(request, identity)


@router.delete(
    "/sessions/{session_id}",
    status_code=202,
    responses={200: {"description": "Session already closed"}},
)
async def end_session(
    request: Request,
    session_id: str,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """End session via CloseSessionCommand through the command system."""
    await refuse_act_on_ancestor(identity, session_id, ACT_END)
    user_agent = request.headers.get("user-agent", "no-ua")
    logger.info(
        "DELETE /sessions/%s (computer=%s, ua=%s)",
        session_id,
        computer,
        user_agent,
    )

    caller = await resolve_caller_provenance(identity)
    if computer and is_remote_target(computer, config.computer.name):
        ownership = await resolve_session_ownership(session_id, db=db, cache=_STATE.cache)
        target_computer: str | None = None
        if isinstance(ownership, RemoteOwnership):
            if ownership.computer != computer:
                raise HTTPException(status_code=404, detail="Session not found on requested computer")
            target_computer = ownership.computer
        elif ownership is None:
            target_computer = computer

        if target_computer is not None:
            # ADR-0036: cross-host close carries no human-origin signal, so it does not hold (scoped out).
            cmd = CloseSessionCommand(session_id=session_id)
            cmd.computer = target_computer
            cmd.caller = caller
            result = await dispatch_caller_command(_STATE.client, cmd, identity)
            if not isinstance(result, dict):
                raise RuntimeError("Remote receipt submission returned no result")
            return _close_accepted(cast(SerializedOperation, result))  # type: ignore[return-value]  # pyright: ignore[reportReturnType]

    # ADR-0036: only a human-initiated close holds the driven todo. A human
    # terminal/TUI caller has an empty identity.session_id; an agent
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
        cmd.caller = caller
        receipt = await get_operations_service().submit(cmd, caller=caller, client_request_id=str(uuid4()))

        return _close_accepted(receipt)  # type: ignore[return-value]  # pyright: ignore[reportReturnType]
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
        occurred_at=datetime.now(UTC),
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
    occurrence_key: str | None = None,
) -> tuple[str, int, int]:
    identity = event_identity or await _resolve_caller_event_identity(caller_session_id)
    header = identity.header if identity is not None else None
    if not header:
        return message_text, 0, 0
    return format_identity_conversation(header=header, body=message_text, occurrence_key=occurrence_key)


async def _process_api_message(
    session_id: str,
    message_text: str,
    metadata: MessageMetadata,
    identity: CallerIdentity,
    occurrence_key: str | None = None,
    computer: str | None = None,
) -> None:
    # guard: loose-dict - CommandMapper.map_api_input payload boundary
    payload: dict[str, object] = {"session_id": session_id, "text": message_text}
    if occurrence_key is not None:
        payload[OCCURRENCE_KEY] = occurrence_key
    cmd = CommandMapper.map_api_input("message", payload, metadata, computer=computer)
    await dispatch_caller_command(_STATE.client, cmd, identity)


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
        await _process_api_message(session_id, request.message, _build_metadata(), identity)

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
        metadata=metadata,
        caller_author=caller_author,
        caller_job_role=caller_job_role,
        occurred_at=occurred_at,
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
    session_id: str,
    request: SendMessageRequest,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(carried_caller),
) -> SendMessageResponseDTO:
    try:
        await refuse_act_on_ancestor(identity, session_id, ACT_SEND_MESSAGE)
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
        caller_session = await db.get_session(identity.session_id) if identity.session_id else None
        if (
            identity.session_id
            and identity.session_id != session_id
            and caller_session
            and caller_session.tmux_session_name
        ):
            try:
                await register_listener(
                    target_session_id=session_id,
                    caller_session_id=identity.session_id,
                    caller_tmux_session=caller_session.tmux_session_name,
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
        occurrence_key = uuid4().hex if caller_resolution is not None else None
        message_text, caller_prefix_len, caller_suffix_len = await _wrap_message_with_origin(
            request.message,
            identity.session_id,
            event_identity,
            occurrence_key,
        )
        if caller_resolution is not None:
            metadata.caller_origin_prefix_len = caller_prefix_len
            metadata.caller_origin_suffix_len = caller_suffix_len
        await _process_api_message(session_id, message_text, metadata, identity, occurrence_key, computer=computer)
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
