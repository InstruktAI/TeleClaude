"""Session management endpoints (list, create, delete, send-message)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, assert_never
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
    carried_caller,
    resolve_caller_provenance,
)
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.api.session_authority import ACT_END, ACT_SEND_MESSAGE, refuse_act_on_dispatching_orchestrator
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
from teleclaude.api.session_listing_route import (
    ListSessionsQuery,
    build_local_session_listing,
    parse_list_sessions_query,
)
from teleclaude.api.session_ownership import LocalOwnership, RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_reminder_summary import attach_next_reminders, observe_session_reminder_summaries
from teleclaude.api.session_remote import is_remote_create_target, is_remote_target
from teleclaude.api.session_route_helpers import build_metadata as _build_metadata
from teleclaude.api.session_route_helpers import close_accepted as _close_accepted
from teleclaude.api.session_route_helpers import (
    dispatch_caller_command,
    envelope_caller_message,
    resolve_caller_event_identity,
)
from teleclaude.api.session_route_helpers import resolve_created_session_transport as _resolve_created_session_transport
from teleclaude.api.session_view_models import project_session_dtos
from teleclaude.api.sessions_actions_routes import guard_generic_create_session
from teleclaude.api.work_feedback import DeclaredWorkRefusal
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    SendMessageRequest,
    SendMessageResponseDTO,
    SessionDTO,
)
from teleclaude.config.machine import config
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.command_input import CommandInputError, CommandInputMode, ResolvedCommandInput
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import (
    DirectLinkExclusivityError,
    SessionMessageRejectedError,
    UnidentifiableCallerError,
)
from teleclaude.core.interactive_procedure_input import (
    InteractiveBinding,
    bind_interactive_input,
    resolve_interactive_input,
)
from teleclaude.core.models import (
    AgentDispatchMode,
    MessageAuthor,
    MessageMetadata,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.core.next_machine.session_hold import hold_todo_for_manual_session_close
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.operations.service import get_operations_service
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
from teleclaude.core.session_status import is_session_final
from teleclaude.core.session_status import is_session_terminal as _terminal
from teleclaude.core.session_utils import resolve_working_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import Session
    from teleclaude.core.reminders import ReminderService
from teleclaude.paths import REPO_ROOT
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
_NO_TMUX_SESSION = ""
_WORKTREE_SUBDIR_TEMPLATE = "trees/{slug}"
_WORKTREE_DIRECTORY_MISSING_TEMPLATE = "required worktree directory does not exist: {worktree_dir}"
_END_SESSION_NOT_HELD_DETAIL = "Session {session_id} not found on {computer}"
_END_SESSION_OWNED_ELSEWHERE_DETAIL = "Session {session_id} not found on {computer}; it is owned by {owner}"


_CONFIG_UNSET = object()
_LIST_SESSIONS_READ = "list_sessions"
_INCLUDE_CLOSED_FIELD = "include_closed"

_STATE = SimpleNamespace(client=None, cache=None, reminder_service=None)

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


async def _prepare_create_session(
    request: CreateSessionRequest,
    identity: CallerIdentity,
    binding: InteractiveBinding | None,
) -> tuple[MessageMetadata, str | None, str | None, SessionLaunchIntent | None, Session | None]:
    """Prepare session creation metadata, initiator ID, and launch intent."""
    initiator_session_id = _extract_initiator_session_id(request, identity)

    origin, caller_email, origin_meta = _resolve_origin(request, identity)

    metadata = _build_metadata(
        origin=origin,
        project_path=request.project_path,
        subdir=request.subdir,
        human_email=caller_email,
        human_role=None,
        origin_metadata=origin_meta,
        role=binding.role if binding is not None else None,
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
    if launch_intent is not None and launch_intent.kind is SessionLaunchKind.AGENT_THEN_MESSAGE and identity.session_id:
        launch_intent.caller_header = (await resolve_caller_event_identity(identity.session_id)).header
    metadata.launch_intent = launch_intent
    return metadata, initiator_session_id, initial_input, launch_intent, direct_caller_session


def _prepare_interactive_create_request(
    request: CreateSessionRequest,
) -> tuple[CreateSessionRequest, InteractiveBinding | None]:
    """Bind local TUI command input before generic-create metadata and guards.

    A leading token naming a published entry procedure is bound under its declared parameters, so the
    guards see the procedure, its declared role and its work item; the session is created through the
    procedure entry on the owning computer. Any other text stays ordinary conversation.
    """
    project_root = Path(request.project_path) if request.project_path else REPO_ROOT
    result = resolve_interactive_input(request.message, request.command_input_mode, project_root)
    if not isinstance(result, ResolvedCommandInput):
        return request, None
    try:
        binding = bind_interactive_input(result, project_root)
    except CommandInputError as exc:
        raise RunSessionRefusal(
            status_code=400,
            detail=str(exc),
            reason=AgentDispatchReason.COMMAND_INVALID,
        ) from exc
    normalized_request = request.model_copy(update={"command_input_source_text": request.message})
    if binding.worktree_bound and binding.working_slug:
        subdir = _WORKTREE_SUBDIR_TEMPLATE.format(slug=binding.working_slug)
        worktree_dir = Path(resolve_working_dir(normalized_request.project_path, subdir))
        if not worktree_dir.is_dir():
            raise RunSessionRefusal(
                status_code=400,
                detail=_WORKTREE_DIRECTORY_MISSING_TEMPLATE.format(worktree_dir=worktree_dir),
                reason=AgentDispatchReason.WORKTREE_MISMATCH,
            )
        normalized_request = normalized_request.model_copy(update={"subdir": subdir})
    return normalized_request, binding


@router.get("/sessions")
async def list_sessions(
    request: Request,
    query: ListSessionsQuery = Depends(parse_list_sessions_query),
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
        caller_session_id = request.headers.get("x-caller-session-id")
        merged, local_session_ids = await build_local_session_listing(
            query,
            _identity,
            caller_session_id=caller_session_id,
            cache=_STATE.cache,
        )

        computer_registry = _STATE.cache.get_computers() if _STATE.cache is not None else []
        dtos = project_session_dtos(
            merged,
            serving_computer=config.computer.name,
            computer_registry=computer_registry,
        )
        dtos = await attach_next_reminders(
            dtos,
            local_session_ids,
            _STATE.reminder_service,
        )
        observe_session_reminder_summaries(dtos)
        return dtos
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
    binding: InteractiveBinding | None = None
    if request.command_input_mode is CommandInputMode.INTERACTIVE_SHORTHAND and not is_remote_create_target(
        request.computer, config.computer.name
    ):
        request, binding = _prepare_interactive_create_request(request)

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
        ) = await _prepare_create_session(request, identity, binding)
    except UnidentifiableCallerError as exc:
        logger.warning(
            _UNIDENTIFIABLE_CALLER_EVENT,
            caller_session_id=exc.caller_session_id,
            ignition_path=_SESSION_START_IGNITION_PATH,
        )
        detail = str(exc)
        raise DeclaredWorkRefusal(
            status_code=exc.http_status_code,
            detail=detail,
            work_feedback=detail,
        ) from exc

    cmd = CommandMapper.map_api_input(
        "new_session",
        {
            "skip_listener_registration": request.skip_listener_registration,
            "initiator_session_id": initiator_session_id,
            "startup_work_expected": bool(request.direct and identity.session_id and request.message),
            "initial_input": initial_input,
            "title": request.title,
            "command": binding.procedure_id if binding is not None else None,
            "working_slug": binding.working_slug if binding is not None else None,
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
        async with guard_generic_create_session(request, cmd, identity) as guard_result:
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
            caller_author, caller_job_role = await _resolve_caller_event_author(identity.session_id)
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
            human_facing=not identity.role and bool(identity.email),
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
    except HTTPException as exc:
        raise exc
    except DirectLinkExclusivityError as exc:
        # Lost the race against a concurrent ignition on this caller: the
        # session exists but stays unlinked rather than becoming a third peer.
        detail = str(exc)
        raise DeclaredWorkRefusal(
            status_code=exc.http_status_code,
            detail=detail,
            work_feedback=detail,
        ) from exc
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


async def _require_held_session(session_id: str) -> Session:
    """Return the session this computer holds, or refuse the request as not found."""
    ownership = await resolve_session_ownership(session_id, db=db, cache=_STATE.cache)
    match ownership:
        case None:
            raise HTTPException(
                status_code=404,
                detail=_END_SESSION_NOT_HELD_DETAIL.format(session_id=session_id, computer=config.computer.name),
            )
        case RemoteOwnership():
            raise HTTPException(
                status_code=404,
                detail=_END_SESSION_OWNED_ELSEWHERE_DETAIL.format(
                    session_id=session_id,
                    computer=config.computer.name,
                    owner=ownership.computer,
                ),
            )
        case LocalOwnership():
            return ownership.session
        case _:
            assert_never(ownership)


@router.delete(
    "/sessions/{session_id}",
    status_code=202,
    responses={
        200: {"description": "Session already closed"},
        404: {"description": "Session not held by the addressed computer"},
    },
)
async def end_session(
    request: Request,
    session_id: str,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """End a session via CloseSessionCommand through the command system.

    A session this computer does not hold is refused as not found (404), naming the
    owning computer when a peer snapshot knows it; nothing is dispatched. An already
    closed session answers 200 without dispatch; any other held session answers 202
    with the close operation receipt.
    """
    await refuse_act_on_dispatching_orchestrator(identity, session_id, ACT_END)
    user_agent = request.headers.get("user-agent", "no-ua")
    logger.info(
        "DELETE /sessions/%s (computer=%s, ua=%s)",
        session_id,
        computer,
        user_agent,
    )

    session = await _require_held_session(session_id)
    caller = await resolve_caller_provenance(identity)

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
        if is_session_final(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
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


async def _resolve_caller_event_author(caller_session_id: str) -> tuple[MessageAuthor, str | None]:
    identity = await resolve_caller_event_identity(caller_session_id)
    return identity.author, identity.job_role


def _listener_caller(identity: CallerIdentity, caller_session: Session | None) -> tuple[str, str] | None:
    """Where a one-shot listener reaches the caller: its tmux session and computer.

    A caller that receives hook delivery is reachable without a host pane; a session
    with none records the empty pane value. A caller session another computer holds
    has no tmux session here; its listener is recorded against the computer its relay
    named, and the outcome is delivered there.
    """
    if caller_session is not None:
        if not caller_session.receives_hook_delivery:
            return None
        return caller_session.tmux_session_name, caller_session.computer_name
    relayed = get_relayed_caller()
    if relayed is not None and relayed.session_id == identity.session_id:
        return _NO_TMUX_SESSION, relayed.computer
    return None


async def _process_api_message(
    session_id: str,
    message_text: str,
    metadata: MessageMetadata,
    identity: CallerIdentity,
    occurrence_key: str | None = None,
) -> None:
    # guard: loose-dict - CommandMapper.map_api_input payload boundary
    payload: dict[str, object] = {"session_id": session_id, "text": message_text}
    if occurrence_key is not None:
        payload[OCCURRENCE_KEY] = occurrence_key
    cmd = CommandMapper.map_api_input("message", payload, metadata)
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
        metadata = _build_metadata()
        message_text, occurrence_key = await envelope_caller_message(metadata, identity, request.message)
        await _process_api_message(session_id, message_text, metadata, identity, occurrence_key)

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
    caller_author, caller_job_role = await _resolve_caller_event_author(identity.session_id)
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
        await refuse_act_on_dispatching_orchestrator(identity, session_id, ACT_SEND_MESSAGE)
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
        listener_caller = _listener_caller(identity, caller_session)
        if identity.session_id and identity.session_id != session_id and listener_caller is not None:
            caller_tmux_session, caller_computer = listener_caller
            try:
                await register_listener(
                    target_session_id=session_id,
                    caller_session_id=identity.session_id,
                    caller_tmux_session=caller_tmux_session,
                    one_shot=True,
                    caller_computer=caller_computer,
                )
            except Exception:
                logger.debug(
                    "One-shot listener registration failed: caller=%s target=%s", identity.session_id, session_id
                )

        message_text, occurrence_key = await envelope_caller_message(metadata, identity, request.message)
        await _process_api_message(session_id, message_text, metadata, identity, occurrence_key)
        return SendMessageResponseDTO(status="success", mode="work")
    except (SessionMessageRejectedError, UnidentifiableCallerError) as exc:
        if isinstance(exc, UnidentifiableCallerError):
            logger.warning("Refused unidentifiable caller: caller=%s target=%s", exc.caller_session_id, session_id)
        detail = str(exc)
        raise DeclaredWorkRefusal(
            status_code=exc.http_status_code,
            detail=detail,
            work_feedback=detail,
        ) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("process_message failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message: {e}") from e
