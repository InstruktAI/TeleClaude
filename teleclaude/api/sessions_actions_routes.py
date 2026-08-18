"""Session action endpoints (keys, voice, file, revive, run, result, escalate)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.agent_dispatch_errors import (
    agent_dispatch_http_refusal,
    emit_run_accepted,
    emit_run_outcome,
    present_routing_explanation,
    run_dispatch_refusal_reason,
    run_refusal_outcome,
)
from teleclaude.api.auth import (
    CallerIdentity,
    clearance_sessions_agent_restart,
    clearance_sessions_escalate,
    clearance_sessions_file,
    clearance_sessions_keys,
    clearance_sessions_result,
    clearance_sessions_revive,
    clearance_sessions_run,
    clearance_sessions_tail,
    clearance_sessions_unsubscribe,
    clearance_sessions_voice,
)
from teleclaude.api.run_session_refusals import RunSessionRefusal, resolve_run_session_agent
from teleclaude.api.run_session_shapes import RunSessionPlan, infer_working_slug
from teleclaude.api.session_access import check_session_access
from teleclaude.api.session_remote import is_remote_target
from teleclaude.api.sessions_coordinate_routes import router as sessions_coordinate_router
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    EscalateRequest,
    FileUploadRequest,
    KeysRequest,
    RunSessionRequest,
    SendResultRequest,
    SessionMessagesDTO,
    VoiceInputRequest,
)
from teleclaude.config import config
from teleclaude.constants import (
    COMMAND_ROLE_MAP,
    NON_SLUG_BOUND_COMMANDS,
    WORKTREE_DIR,
    DriverLaunchClass,
    SlashCommand,
)
from teleclaude.core import agents as agents_module
from teleclaude.core.agent_dispatch import (
    AgentDispatchFailure,
    AgentDispatchReason,
    RunSessionThinkingMode,
    decision_basis_digest,
    resolve_run_session_thinking_mode,
)
from teleclaude.core.agents import get_known_agents
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.command_dispatch import (
    dispatch_command,
    parse_remote_dispatch_data_diagnosed,
)
from teleclaude.core.command_handlers import resolve_working_slug_from_subdir
from teleclaude.core.command_mapper import KEY_COMMANDS, CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.command_service import DISPATCH_ALLOWED, classify_driver_launch
from teleclaude.core.db import db
from teleclaude.core.models import (
    AgentDispatchMode,
    MessageMetadata,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata, WebOriginMetadata
from teleclaude.core.models._types import SessionOriginMetadata
from teleclaude.core.next_machine.manual_start import DriverStartGuardResult, guard_driver_start
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_message_projection import (
    SessionMessageProjectionOptions,
    build_session_messages_dto,
)
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.core.todos_db._exceptions import ClaimConflict, ReviewerConflict, ReviewerIdentityUnresolved
from teleclaude.types.commands import CreateSessionCommand, UnsubscribeSessionCommand
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id, recover_native_project

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
from teleclaude.types.commands import ResponseMode, SystemCommand

logger = get_logger(__name__)

WORKER_LIFECYCLE_COMMANDS = {
    SlashCommand.NEXT_BUILD,
    SlashCommand.NEXT_REVIEW_BUILD,
    SlashCommand.NEXT_FINALIZE,
}

WORKTREE_BOUND_WORKER_COMMANDS = {
    SlashCommand.NEXT_BUILD,
    SlashCommand.NEXT_REVIEW_BUILD,
    SlashCommand.NEXT_FINALIZE,
}

NON_TODO_ARGUMENT_COMMANDS = {SlashCommand.NEXT_REVIEW_COMMITS}

SLUG_INFERABLE_LIFECYCLE_COMMANDS = {
    command.value for command in COMMAND_ROLE_MAP if command not in NON_TODO_ARGUMENT_COMMANDS
}
SLUG_INFERABLE_LIFECYCLE_COMMANDS.add("analyze-todo-input")

SLUG_REQUIRED_LIFECYCLE_COMMANDS = SLUG_INFERABLE_LIFECYCLE_COMMANDS - {
    command.value for command in NON_SLUG_BOUND_COMMANDS
}
WORKING_SLUG_LIFECYCLE_COMMANDS = SLUG_INFERABLE_LIFECYCLE_COMMANDS | {SlashCommand.NEXT_PREPARE.value}

REMOTE_SESSION_MESSAGES_COMMAND = "get_session_messages"
NO_REMOTE_COMPUTER = ""

_STATE = SimpleNamespace(client=None)

router = APIRouter()
router.include_router(sessions_coordinate_router)


def configure(client: AdapterClient | None = None) -> None:
    """Wire client; called from APIServer at construction."""
    if client is not None:
        _STATE.client = client


def _build_metadata(*, origin: str = InputOrigin.TERMINAL.value, **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def _native_session_exists_for_agent(native_session_id: str, agent: str) -> bool:
    """Return whether a native session ID resolves for the requested agent."""
    if not native_session_id:
        return False

    try:
        agent_name = agents_module.AgentName.from_str(agent)
    except ValueError:
        return False

    if agent_name is agents_module.AgentName.CODEX:
        return discover_codex_transcript_path(native_session_id) is not None

    for transcript in discover_transcripts([agent_name]):
        if extract_session_id(transcript.path, agent_name) == native_session_id:
            return True
    return False


@dataclass(frozen=True)
class SessionMessagesQuery:
    """Normalized query parameters for message retrieval."""

    computer: str | None = None
    since: str | None = None
    include_tools: bool | None = None
    include_thinking: bool = False
    tail_chars: int = 10000
    tail_scope: str = "all"


def _parse_session_messages_query(
    computer: str | None = Query(None, description="Target computer"),
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; only messages after this time"),
    include_tools: bool | None = Query(None, description="Include tool invocation entries when policy allows them"),
    include_thinking: bool = Query(False, description="Include thinking/reasoning blocks"),
    tail_chars: int = Query(10000, description="Fallback char budget for tmux/session tail output"),
    tail_scope: str = Query("all", description="Message window: all or latest_turn"),
) -> SessionMessagesQuery:
    """Collect session-messages query parameters into one object."""
    return SessionMessagesQuery(
        computer=computer,
        since=since,
        include_tools=include_tools,
        include_thinking=include_thinking,
        tail_chars=tail_chars,
        tail_scope=tail_scope,
    )


async def _resolve_revive_session_id(
    http_request: Request,
    session_id: str,
    agent: str | None,
    identity: CallerIdentity,
) -> str:
    """Resolve a TeleClaude session id for revive requests.

    When an agent is specified and no existing DB mapping exists, validates that the
    native session ID resolves on the agent's filesystem before creating a new session.
    Raises HTTPException(404) if the native ID cannot be found.
    """
    if not agent:
        return session_id

    resolved = await db.get_session_by_field("native_session_id", session_id, include_initializing=True)
    if resolved:
        if resolved.active_agent and resolved.active_agent != agent:
            raise HTTPException(
                status_code=409,
                detail=f"Native session belongs to agent '{resolved.active_agent}', not '{agent}'",
            )
        return resolved.session_id

    if not _native_session_exists_for_agent(session_id, agent):
        raise HTTPException(status_code=404, detail=f"Native session ID is not valid for agent '{agent}'")

    new_session_id = str(uuid.uuid4())
    project_path: str | None = None
    subdir: str | None = None
    title: str | None = None
    origin_context = await db.get_origin_revival_context_for_native_session(session_id)
    if origin_context is not None:
        project_path, subdir, title = origin_context.project_path, origin_context.subdir, origin_context.title
    else:
        agent_name = agents_module.AgentName.from_str(agent)
        caller_cwd = http_request.query_params.get("project")
        recovered_project = recover_native_project(session_id, agent_name, caller_cwd)
        if recovered_project is None:
            raise HTTPException(
                status_code=422,
                detail="Cannot locate the native session's project; re-run revive from that project directory",
            )
        trusted_dirs = [trusted_dir.path for trusted_dir in config.computer.get_all_trusted_dirs()]
        project_path, subdir = split_project_path_and_subdir(recovered_project, trusted_dirs)

    cmd = CreateSessionCommand(
        session_id=new_session_id,
        headless=True,
        native_session_id=session_id,
        native_log_file=None,
        project_path=project_path or "",
        subdir=subdir,
        title=title,
        origin=InputOrigin.TERMINAL.value,
        initiator_session_id=identity.session_id or None,
        initiator_computer=config.computer.name if identity.session_id else None,
        origin_metadata=TerminalOriginMetadata(email=identity.email) if identity.email else None,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=agent,
            native_session_id=session_id,
            dispatch_mode=AgentDispatchMode.FIXED,
        ),
        entry_point=SessionEntryPoint.SYSTEM,
    )
    await get_command_service().create_session(cmd)
    return new_session_id


def _leading_command(message: str | None) -> str | None:
    """Return the leading slash command of a launch message, if any."""
    return message.split()[0] if message and message.startswith("/") else None


def _normalize_command(command: str | None) -> SlashCommand | None:
    """Parse a door-supplied launch command into its canonical `SlashCommand` value.

    Both create doors supply the command slash-prefixed (`_leading_command`'s
    return value, or the run door's `request.command`). Normalizing once here —
    the same way :func:`classify_driver_launch` parses a string command — gives
    the guard a single value to key both the title-prefix lookup and the
    reuse-command text from, so the two consumers can never disagree on shape.
    """
    if command is None:
        return None
    try:
        return SlashCommand(command.lstrip("/"))
    except ValueError:
        return None


async def enforce_driver_start_guard(
    *,
    project_path: str,
    working_slug: str | None,
    command: str | None,
    caller_session_id: str | None,
) -> DriverStartGuardResult:
    """Refuse a create-door driver start that would duplicate a live driver.

    Shared by both create doors (run-session and generic create): it classifies
    the requested launch and runs the two-signal dedup guard, mapping a conflict
    to HTTP 409 naming the holder. A non-driver launch or an unclaimed slug passes
    through silently — except a reviewer launch, which is checked even with no
    slug (commit review carries no todo slug at all).
    """
    normalized_command = _normalize_command(command)
    launch_class = classify_driver_launch(normalized_command)
    if launch_class is not DriverLaunchClass.REVIEWER and not working_slug:
        return DriverStartGuardResult()
    try:
        return await guard_driver_start(
            project_path,
            working_slug,
            launch_class=launch_class,
            caller_session_id=caller_session_id,
            command=normalized_command,
        )
    except ReviewerConflict as conflict:
        raise RunSessionRefusal(
            status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.REVIEWER_CONFLICT
        ) from conflict
    except (ClaimConflict, ReviewerIdentityUnresolved) as conflict:
        raise RunSessionRefusal(
            status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.RUN_REQUEST_REJECTED
        ) from conflict


async def guard_generic_create_session(
    request: CreateSessionRequest,
    cmd: object,
    identity: CallerIdentity,
) -> DriverStartGuardResult:
    """Guard the generic ``POST /sessions`` create door against a duplicate driver.

    Resolves the would-be ``working_slug`` from the request the same way the
    create-session primitive does (the "trees/<slug>" worktree subdir, else the
    command's own slug) and runs the shared driver-start guard.
    """
    if not isinstance(cmd, CreateSessionCommand):
        return DriverStartGuardResult()
    return await enforce_driver_start_guard(
        project_path=request.project_path,
        working_slug=resolve_working_slug_from_subdir(request.subdir) or cmd.working_slug,
        command=_leading_command(request.message),
        caller_session_id=identity.session_id,
    )


def _prepare_run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
    entry_point: SessionEntryPoint,
) -> RunSessionPlan:
    """Normalize run-session inputs into a create-session plan."""
    effective_agent = resolve_run_session_agent(request)
    normalized_cmd = request.command.lstrip("/")
    normalized_args = request.args.strip()
    full_command = f"/{normalized_cmd} {normalized_args}" if normalized_args else f"/{normalized_cmd}"
    startup_message = full_command
    if request.additional_context:
        full_command = f"{full_command}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"
        startup_message = f"{startup_message}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"

    initiator_session_id: str | None = None
    if identity.session_id and not identity.session_id.startswith("web:"):
        initiator_session_id = identity.session_id
    if normalized_cmd in WORKER_LIFECYCLE_COMMANDS:
        if not normalized_args:
            raise RunSessionRefusal(
                status_code=400,
                detail=f"/{normalized_cmd} requires a slug argument",
                reason=AgentDispatchReason.SLUG_REQUIRED,
            )
    working_slug = infer_working_slug(normalized_cmd, normalized_args)
    if normalized_cmd in SLUG_REQUIRED_LIFECYCLE_COMMANDS and not working_slug:
        raise RunSessionRefusal(
            status_code=400,
            detail=f"/{normalized_cmd} requires a slug argument",
            reason=AgentDispatchReason.SLUG_REQUIRED,
        )
    if normalized_cmd in WORKTREE_BOUND_WORKER_COMMANDS:
        expected_subfolder = f"{WORKTREE_DIR}/{working_slug}"
        if request.subfolder != expected_subfolder:
            actual_subfolder = request.subfolder or "<empty>"
            raise RunSessionRefusal(
                status_code=400,
                detail=(
                    f"/{normalized_cmd} for slug '{working_slug}' requires subfolder "
                    f"'{expected_subfolder}', received '{actual_subfolder}'"
                ),
                reason=AgentDispatchReason.WORKTREE_MISMATCH,
            )

    origin_metadata: WebOriginMetadata | None = None
    if identity.email:
        origin_metadata = WebOriginMetadata(email=identity.email)

    try:
        slash_cmd = SlashCommand(normalized_cmd)
    except ValueError:
        slash_cmd = None
    role_info = COMMAND_ROLE_MAP.get(slash_cmd) if slash_cmd else None

    if role_info and identity.system_role:
        target_role = role_info[0]
        allowed = DISPATCH_ALLOWED.get(identity.system_role, frozenset())
        if target_role not in allowed:
            raise RunSessionRefusal(
                status_code=403,
                detail=(
                    f"role '{identity.system_role}' cannot dispatch /{normalized_cmd} "
                    f"(requires dispatch privilege for '{target_role}')"
                ),
                reason=AgentDispatchReason.DISPATCH_PRIVILEGE_FORBIDDEN,
            )

    thinking_mode = resolve_run_session_thinking_mode(
        caller_mode=(RunSessionThinkingMode(request.thinking_mode) if request.thinking_mode is not None else None),
        job_role=role_info[1].value if role_info else None,
    )

    return RunSessionPlan(
        effective_agent=effective_agent,
        full_command=full_command,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            agent=effective_agent,
            thinking_mode=thinking_mode.value,
            message=startup_message,
            dispatch_mode=(AgentDispatchMode.MANUAL_PREFERENCE if effective_agent else AgentDispatchMode.AUTOMATIC),
        ),
        initiator_session_id=initiator_session_id,
        origin_metadata=origin_metadata,
        system_role=role_info[0] if role_info else None,
        job=role_info[1].value if role_info else None,
        working_slug=working_slug,
        entry_point=entry_point,
    )


@router.post("/sessions/{session_id}/keys")
async def send_keys_endpoint(
    http_request: Request,
    session_id: str,
    request: KeysRequest,
    computer: str | None = Query(None),
    _identity: CallerIdentity = Depends(clearance_sessions_keys),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send key command to session."""
    await check_session_access(http_request, session_id)
    try:
        args: list[str] = []
        if request.count:
            args = [str(request.count)]
        if request.key not in KEY_COMMANDS:
            raise HTTPException(status_code=400, detail=f"Unsupported key command: {request.key}")
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "keys",
            {"session_id": session_id, "key": request.key, "args": args},
            metadata,
            computer=computer,
        )
        await dispatch_command(_STATE.client, cmd)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("send_keys failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send keys: {e}") from e


@router.post("/sessions/{session_id}/voice")
async def send_voice_endpoint(
    http_request: Request,
    session_id: str,
    request: VoiceInputRequest,
    computer: str | None = Query(None),
    _identity: CallerIdentity = Depends(clearance_sessions_voice),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send voice input to session."""
    await check_session_access(http_request, session_id)
    try:
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "handle_voice",
            {
                "session_id": session_id,
                "file_path": request.file_path,
                "duration": request.duration,
                "message_id": request.message_id,
                "message_thread_id": request.message_thread_id,
            },
            metadata,
            computer=computer,
        )
        await dispatch_command(_STATE.client, cmd)
        return {"status": "success"}
    except Exception as e:
        logger.error("send_voice failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send voice: {e}") from e


@router.post("/sessions/self/file")
async def send_file_endpoint(
    request: FileUploadRequest,
    identity: CallerIdentity = Depends(clearance_sessions_file),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send a file attachment to the session's user."""
    session_id = identity.session_id
    cmd = SystemCommand(
        command="deliver_file",
        session_id=session_id,
        data={
            "file_path": request.file_path,
            "filename": request.filename,
            "caption": request.caption,
            "file_size": request.file_size,
        },
    )
    try:
        return await get_command_service().deliver_file(cmd)  # type: ignore[return-value]
    except Exception as e:
        logger.error("send_file failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send file: {e}") from e


@router.post("/sessions/{session_id}/agent-restart", status_code=202)
async def agent_restart(
    http_request: Request,
    session_id: str,
    computer: str | None = Query(None),
    _identity: CallerIdentity = Depends(clearance_sessions_agent_restart),
) -> dict[str, str]:
    """Restart agent in session (preserves conversation via --resume)."""
    await check_session_access(http_request, session_id)
    try:
        logger.info("API agent_restart requested (session=%s, origin=api)", session_id)

        # Quick validation before dispatching
        if not is_remote_target(computer, config.computer.name):
            session = await db.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if not session.active_agent:
                raise HTTPException(status_code=409, detail="No active agent for this session")
            if not session.native_session_id:
                raise HTTPException(status_code=409, detail="No native session ID - start agent first")

        # Dispatch work asynchronously - don't await
        body = await http_request.json() if http_request.headers.get("content-type") == "application/json" else {}
        self_restart = bool(body.get("self_restart")) if isinstance(body, dict) else False
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "agent_restart",
            {"session_id": session_id, "args": [], "self_restart": self_restart},
            metadata,
            computer=computer,
        )
        asyncio.create_task(dispatch_command(_STATE.client, cmd), name=f"agent-restart-{session_id}")
        return {"status": "accepted", "completion_event": cmd.completion_event or "agent.restart_dispatched"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_restart failed for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to restart agent: {e}") from e


@router.post("/sessions/{session_id}/revive")
async def revive_session(
    http_request: Request,
    session_id: str,
    agent: str | None = Query(None, description="When provided, session_id is a native agent session ID"),
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(clearance_sessions_revive),
) -> CreateSessionResponseDTO:
    """Revive a session by TeleClaude or native session ID."""
    session_id = await _resolve_revive_session_id(http_request, session_id, agent, identity)
    await check_session_access(http_request, session_id)
    try:
        session = await db.get_session(session_id)
        if not is_remote_target(computer, config.computer.name):
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if not session.active_agent:
                raise HTTPException(status_code=409, detail="No active agent for this session")
            if not session.native_session_id:
                raise HTTPException(status_code=409, detail="No native session ID - start agent first")

        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "agent_restart",
            {"session_id": session_id, "args": []},
            metadata,
            computer=computer,
        )
        cmd.response_mode = ResponseMode.IMMEDIATE
        cmd.completion_event = None
        result = await dispatch_command(_STATE.client, cmd)
        if isinstance(result, tuple | list) and len(result) >= 2:
            success = bool(result[0])
            error = str(result[1]) if result[1] else None
        else:
            success, error = (True, None)
        if not success:
            detail = error or "Failed to revive session"
            raise HTTPException(status_code=409, detail=detail)

        refreshed = await db.get_session(session_id)
        tmux_session_name = refreshed.tmux_session_name if refreshed and refreshed.tmux_session_name else ""
        return CreateSessionResponseDTO(
            status="success",
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            computer=computer if is_remote_target(computer, config.computer.name) else None,
            agent=session.active_agent if session and session.active_agent in get_known_agents() else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("revive_session failed for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revive session: {e}") from e


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    request: Request,
    session_id: str,
    query: SessionMessagesQuery = Depends(_parse_session_messages_query),
    _identity: CallerIdentity = Depends(clearance_sessions_tail),
) -> SessionMessagesDTO:
    """Get structured messages from a session's transcript files."""
    await check_session_access(request, session_id)

    try:
        options = SessionMessageProjectionOptions(
            since=query.since,
            include_tools=query.include_tools,
            include_thinking=query.include_thinking,
            tail_chars=query.tail_chars,
            tail_scope=query.tail_scope,
        )
        if is_remote_target(query.computer, config.computer.name):
            if _STATE.client is None:
                raise HTTPException(status_code=503, detail="Remote session tail is unavailable")
            target_computer = query.computer or NO_REMOTE_COMPUTER
            tail_origin_metadata = cast(
                SessionOriginMetadata,
                {
                    "since": query.since,
                    "include_tools": query.include_tools,
                    "include_thinking": query.include_thinking,
                    "tail_chars": query.tail_chars,
                    "tail_scope": query.tail_scope,
                },
            )
            metadata = MessageMetadata(
                origin_metadata=tail_origin_metadata,
                human_email=_identity.email,
                human_role=_identity.human_role,
            )
            message_id = await _STATE.client.send_request(
                target_computer,
                REMOTE_SESSION_MESSAGES_COMMAND,
                metadata,
                session_id=session_id,
            )
            response_text = await _STATE.client.read_response(message_id, target_computer=target_computer)
            data = await parse_remote_dispatch_data_diagnosed(
                _STATE.client,
                response_text,
                target_computer=target_computer,
                command=REMOTE_SESSION_MESSAGES_COMMAND,
            )
            return SessionMessagesDTO.model_validate(data)

        return await build_session_messages_dto(
            session_id,
            recipient_email=_identity.email,
            recipient_role=_identity.human_role,
            options=options,
            database=db,
            command_service=get_command_service(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_session_messages failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {e}") from e


# =====================================================================
# Tool CLI endpoints (require dual-factor auth via verify_caller)
# =====================================================================


async def _run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
    *,
    entry_point: SessionEntryPoint,
) -> CreateSessionResponseDTO:
    """Run a slash command on a new agent session.

    Creates a new session with a typed launch intent derived from the given
    slash command, arguments, project, agent, and thinking mode.
    Clearance is enforced by the clearance_sessions_run dependency.
    """
    request_id = str(uuid.uuid4())
    normalized_command = request.command.lstrip("/") if request.command.startswith("/") else None
    command_kind = "prepare" if normalized_command == SlashCommand.NEXT_PREPARE.value else normalized_command
    producer_agent: str | None = None
    try:
        requested_command = SlashCommand(normalized_command) if normalized_command else None
    except ValueError:
        requested_command = None
    role_info = COMMAND_ROLE_MAP.get(requested_command) if requested_command else None
    if (
        role_info
        and role_info[1].value == "reviewer"
        and identity.session_id
        and not identity.session_id.startswith("web:")
    ):
        producer = await db.get_session(identity.session_id)
        producer_agent = producer.active_agent if producer is not None else None
    agent_supplied = "agent" in request.model_fields_set
    dispatch_mode = AgentDispatchMode.MANUAL_PREFERENCE if agent_supplied else AgentDispatchMode.AUTOMATIC
    preferred_agent = request.agent if dispatch_mode is AgentDispatchMode.MANUAL_PREFERENCE else None
    fixed_agent = None
    basis_digest = decision_basis_digest(
        mode=dispatch_mode,
        role=role_info[1].value if role_info else None,
        todo_kind=None,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        producer_agent=producer_agent,
    )
    dispatch_mode = emit_run_accepted(
        request_id=request_id,
        agent_supplied=agent_supplied,
        entry_point=entry_point,
        command_kind=command_kind,
        working_slug_present=bool(normalized_command and infer_working_slug(normalized_command, request.args.strip())),
        caller_kind_present=False,
        producer_agent=producer_agent,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        decision_basis_digest=basis_digest,
    )
    try:
        if not request.command.startswith("/"):
            raise RunSessionRefusal(
                status_code=400, detail="command must start with '/'", reason=AgentDispatchReason.COMMAND_INVALID
            )
        if not request.project:
            raise RunSessionRefusal(
                status_code=400, detail="project required", reason=AgentDispatchReason.PROJECT_REQUIRED
            )
        plan = _prepare_run_session(request, identity, entry_point)
    except RunSessionRefusal as exc:
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
        )
        raise
    except AgentDispatchFailure as exc:
        refusal = agent_dispatch_http_refusal(exc)
        if refusal is None:
            raise
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
            error=True,
        )
        raise refusal from exc

    metadata = _build_metadata(
        project_path=request.project,
        subdir=request.subfolder or None,
        origin_metadata=plan.origin_metadata,
        system_role=plan.system_role,
        job=plan.job,
    )
    metadata.launch_intent = plan.launch_intent

    cmd = CommandMapper.map_api_input(
        "new_session",
        {
            "skip_listener_registration": request.detach,
            "initiator_session_id": plan.initiator_session_id,
            "initial_input": plan.full_command,
        },
        metadata,
        computer=request.computer,
    )
    if isinstance(cmd, CreateSessionCommand):
        cmd.working_slug = plan.working_slug
        cmd.entry_point = plan.entry_point
        cmd.request_id = request_id
        if cmd.launch_intent is not None:
            cmd.launch_intent.accepted_at_origin = True
        cmd.producer_agent = producer_agent
    try:
        guard_result = await enforce_driver_start_guard(
            project_path=request.project,
            working_slug=plan.working_slug,
            command=request.command,
            caller_session_id=plan.initiator_session_id,
        )
    except RunSessionRefusal as exc:
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=plan.entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
        )
        raise
    success_reason = (
        AgentDispatchReason.HELD_WITHOUT_DRIVER
        if guard_result.held_without_driver
        else AgentDispatchReason.DISPATCH_PRIVILEGE_ALLOWED
        if plan.job and identity.system_role
        else AgentDispatchReason.WORKING_SLUG_INFERRED
        if plan.working_slug
        else None
    )
    try:
        data = await dispatch_command(_STATE.client, cmd)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="Failed to create session")
        session_id = data.get("session_id")
        tmux_session_name = data.get("tmux_session_name")
        if not session_id or not tmux_session_name:
            raise HTTPException(status_code=500, detail="Failed to create session")
        routing_explanation = present_routing_explanation(
            data,
            human_facing=not identity.system_role and bool(identity.email),
            request_id=cmd.request_id,
            session_id=str(session_id),
            entry_point=plan.entry_point,
        )
        emit_run_outcome(
            selected_agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
            request_id=cmd.request_id,
            session_id=str(session_id),
            entry_point=plan.entry_point,
            dispatch_mode=dispatch_mode,
            reason=success_reason,
            working_slug_present=True if success_reason is AgentDispatchReason.WORKING_SLUG_INFERRED else None,
        )
        return CreateSessionResponseDTO(
            status="success",
            session_id=str(session_id),
            tmux_session_name=str(tmux_session_name),
            computer=request.computer if is_remote_target(request.computer, config.computer.name) else None,
            agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
            routing_explanation=routing_explanation,
        )
    except HTTPException:
        raise
    except Exception as e:
        refusal = agent_dispatch_http_refusal(e)
        if refusal:
            reason = run_dispatch_refusal_reason(e)
            if reason is not None:
                emit_run_outcome(
                    selected_agent=None,
                    request_id=cmd.request_id,
                    entry_point=plan.entry_point,
                    dispatch_mode=dispatch_mode,
                    outcome=run_refusal_outcome(reason),
                    reason=reason,
                )
            raise refusal from e
        logger.error("run_session failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run session: {e}") from e


@router.post("/sessions/run", response_model_exclude_none=True)
async def run_session(
    request: RunSessionRequest,
    identity: CallerIdentity = Depends(clearance_sessions_run),
) -> CreateSessionResponseDTO:
    """Run a public request with API-created provenance only."""
    return await _run_session(request, identity, entry_point=SessionEntryPoint.RUN_SESSION_API)


@router.post("/sessions/{session_id}/unsubscribe")
async def unsubscribe_session(
    session_id: str,
    computer: str | None = Query(None),
    identity: CallerIdentity = Depends(clearance_sessions_unsubscribe),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Stop caring about a target session — umbrella verb across both subscription axes.

    Removes the caller's listener row (if any) AND severs any active direct link
    the caller holds with the target. Idempotent: empty state returns success
    with both action flags false. See `project/spec/session-subscriptions`.
    """
    cmd = UnsubscribeSessionCommand(session_id=session_id, caller_session_id=identity.session_id)
    cmd.computer = computer
    result = await dispatch_command(_STATE.client, cmd)
    if isinstance(result, dict):
        return {"status": "success", **result}
    return {"status": "success", "listener_removed": False, "link_closed": False, "link_id": None}


@router.post("/sessions/self/result")
async def send_result_endpoint(
    request: SendResultRequest,
    identity: CallerIdentity = Depends(clearance_sessions_result),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send a formatted result to the session's user as a separate message.

    Dispatches through CommandService.deliver_result() which handles adapter
    delivery with formatting fallback. Requires dual-factor caller identity.
    """
    cmd = SystemCommand(
        command="deliver_result",
        session_id=identity.session_id,
        data={"content": request.content, "output_format": request.output_format},
    )
    try:
        return await get_command_service().deliver_result(cmd)  # type: ignore[return-value]
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/sessions/self/escalate")
async def escalate_session(
    request: EscalateRequest,
    identity: CallerIdentity = Depends(clearance_sessions_escalate),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Escalate a customer session to an admin via Discord.

    Dispatches through CommandService.escalate_session() as a FIRE_AND_FORGET
    SystemCommand. Returns 202 with completion_event. Requires dual-factor
    caller identity.
    """
    cmd = SystemCommand(
        command="escalate_session",
        session_id=identity.session_id,
        data={
            "customer_name": request.customer_name,
            "reason": request.reason,
            "context_summary": request.context_summary,
        },
        response_mode=ResponseMode.FIRE_AND_FORGET,
        completion_event="session.escalation_started",
    )
    try:
        result = await get_command_service().escalate_session(cmd)
        return JSONResponse(  # type: ignore[return-value]  # pyright: ignore[reportReturnType]
            status_code=202,
            content={
                "status": "accepted",
                "thread_id": result.get("thread_id") if isinstance(result, dict) else None,  # type: ignore[union-attr]
                "completion_event": cmd.completion_event,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
