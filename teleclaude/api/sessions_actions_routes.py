"""Session action endpoints (keys, voice, file, revive, run, result, widget, escalate)."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import frontmatter
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

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
    clearance_sessions_widget,
)
from teleclaude.api.codex_startup_message import _rewrite_codex_next_startup_message
from teleclaude.api.session_access import check_session_access
from teleclaude.api.session_remote import dispatch_session_keys_to_peer, is_remote_target
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    EscalateRequest,
    FileUploadRequest,
    KeysRequest,
    MessageDTO,
    RenderWidgetRequest,
    RunSessionRequest,
    SendResultRequest,
    SessionMessagesDTO,
    VoiceInputRequest,
)
from teleclaude.config import config
from teleclaude.constants import NON_SLUG_BOUND_COMMANDS, SlashCommand
from teleclaude.core import agents as agents_module
from teleclaude.core.agents import assert_agent_enabled, get_default_agent, get_known_agents
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.command_handlers import resolve_working_slug_from_subdir
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.command_service import COMMAND_ROLE_MAP, DISPATCH_ALLOWED, classify_driver_launch
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.models._adapter import TerminalOriginMetadata, WebOriginMetadata
from teleclaude.core.next_machine.manual_start import guard_driver_start
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import close_link_for_member, unregister_listener
from teleclaude.core.session_status import compute_agent_status
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.core.todos_db._exceptions import ClaimConflict
from teleclaude.output_projection import conversation_projector as conversation_projector_module
from teleclaude.output_projection import serializers as output_serializers
from teleclaude.output_projection.models import ProjectionSurface, visibility_policy_for_person
from teleclaude.types.commands import CreateSessionCommand, GetSessionDataCommand
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
from teleclaude.paths import COMMANDS_DIR
from teleclaude.types.commands import ResponseMode, SystemCommand

logger = get_logger(__name__)

WORKER_LIFECYCLE_COMMANDS = {
    SlashCommand.NEXT_BUILD,
    SlashCommand.NEXT_REVIEW_BUILD,
    SlashCommand.NEXT_FIX_REVIEW,
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

_STATE = SimpleNamespace(client=None)

router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire client; called from APIServer at construction."""
    if client is not None:
        _STATE.client = client


def _build_metadata(*, origin: str = InputOrigin.TERMINAL.value, **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def _resolve_command_domain_field(normalized_cmd: str) -> str | None:
    """Return the deployed command's ``domain:`` frontmatter, if any.

    The build stamps ``domain`` onto a command whose role procedure declares
    ``needs_domain_baseline: true`` (see ``scripts/distribute.py``). Frontmatter
    survives inline expansion — the procedure ``@``-ref does not — so dispatch
    resolves the injected baseline from this field. Commands whose procedures make
    no such request carry no ``domain`` and trigger no injection.
    """
    name = normalized_cmd.strip()
    if not name:
        return None
    candidate = COMMANDS_DIR / f"{name}.md"
    if not candidate.exists():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        domain = frontmatter.loads(text).metadata.get("domain")
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    return domain if isinstance(domain, str) and domain else None


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

    since: str | None = None
    include_tools: bool | None = None
    include_thinking: bool = False
    tail_chars: int = 10000
    tail_scope: str = "all"


def _parse_session_messages_query(
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; only messages after this time"),
    include_tools: bool | None = Query(None, description="Include tool invocation entries when policy allows them"),
    include_thinking: bool = Query(False, description="Include thinking/reasoning blocks"),
    tail_chars: int = Query(10000, description="Fallback char budget for tmux/session tail output"),
    tail_scope: str = Query("all", description="Message window: all or latest_turn"),
) -> SessionMessagesQuery:
    """Collect session-messages query parameters into one object."""
    return SessionMessagesQuery(
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
    origin_project = await db.get_origin_project_for_native_session(session_id)
    if origin_project is not None:
        project_path, subdir = origin_project
    else:
        raw_project = http_request.query_params.get("project")
        if raw_project:
            trusted_dirs = [trusted_dir.path for trusted_dir in config.computer.get_all_trusted_dirs()]
            project_path, subdir = split_project_path_and_subdir(raw_project, trusted_dirs)

    cmd = CreateSessionCommand(
        session_id=new_session_id,
        headless=True,
        native_session_id=session_id,
        native_log_file=None,
        project_path=project_path or "",
        subdir=subdir,
        origin=InputOrigin.TERMINAL.value,
        initiator_session_id=identity.session_id or None,
        origin_metadata=TerminalOriginMetadata(email=identity.email) if identity.email else None,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=agent,
            native_session_id=session_id,
        ),
    )
    await get_command_service().create_session(cmd)
    return new_session_id


def _build_message_chain(transcript_files: str | None, native_log_file: str | None) -> list[str]:
    """Build transcript chain from stored session fields."""
    chain: list[str] = []
    if transcript_files:
        try:
            stored = json.loads(transcript_files)
            if isinstance(stored, list):
                chain = [str(path) for path in stored if path]
        except (json.JSONDecodeError, TypeError):
            pass
    if native_log_file and native_log_file not in chain:
        chain.append(native_log_file)
    return chain


def _project_session_messages(
    chain: list[str],
    *,
    active_agent: str | None,
    recipient_email: str | None,
    recipient_role: str | None,
    include_tools: bool | None,
    include_thinking: bool,
    since: str | None,
) -> list[MessageDTO]:
    """Project transcript files into structured messages."""
    if not chain:
        return []

    policy = visibility_policy_for_person(
        human_role=recipient_role,
        person_email=recipient_email,
        surface=ProjectionSurface.WEB,
        include_thinking=include_thinking,
    )
    if include_tools is False:
        policy = replace(policy, include_tools=False)

    projected_blocks = conversation_projector_module.project_conversation_chain(
        chain,
        agents_module.resolve_parser_agent(active_agent),
        policy,
        since=since,
    )
    return [
        MessageDTO(
            role=message.role,
            type=message.type,
            text=message.text,
            timestamp=message.timestamp,
            entry_index=message.entry_index,
            file_index=message.file_index,
        )
        for message in (
            output_serializers.to_structured_message(projected_block) for projected_block in projected_blocks
        )
    ]


def _apply_session_tail_scope(messages: list[MessageDTO], tail_scope: str) -> list[MessageDTO]:
    """Apply a caller-requested message window to already projected messages."""
    if tail_scope != "latest_turn":
        return messages

    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return messages[index:]
    return messages


@dataclass(frozen=True)
class RunSessionPlan:
    """Normalized data needed to create a run-session request."""

    effective_agent: str
    full_command: str
    launch_intent: SessionLaunchIntent
    initiator_session_id: str | None
    origin_metadata: WebOriginMetadata | None
    system_role: str | None
    job: str | None
    working_slug: str | None


def _infer_role_from_message(  # pyright: ignore[reportUnusedFunction]
    message: str | None,
) -> tuple[str | None, str | None]:
    """Infer system_role and job from a slash command at the start of a message."""
    if not message or not message.startswith("/"):
        return None, None
    cmd_token = message.split()[0].lstrip("/")
    try:
        slash_cmd = SlashCommand(cmd_token)
    except ValueError:
        return None, None
    role_info = COMMAND_ROLE_MAP.get(slash_cmd)
    if role_info:
        return role_info[0], role_info[1].value
    return None, None


def _resolve_run_session_agent(request: RunSessionRequest) -> str:
    """Resolve the agent used for a run-session request."""
    if "agent" in request.model_fields_set:
        try:
            return assert_agent_enabled(request.agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return get_default_agent()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _infer_working_slug(normalized_cmd: str, normalized_args: str) -> str | None:
    """Infer the todo slug owned by a lifecycle slash-command session."""
    if normalized_cmd not in WORKING_SLUG_LIFECYCLE_COMMANDS:
        return None
    slug, _, _rest = normalized_args.partition(" ")
    return slug.strip() or None


def _leading_command(message: str | None) -> str | None:
    """Return the leading slash command of a launch message, if any."""
    return message.split()[0] if message and message.startswith("/") else None


async def enforce_driver_start_guard(
    *,
    project_path: str,
    working_slug: str | None,
    command: str | None,
    caller_session_id: str | None,
) -> None:
    """Refuse a create-door driver start that would duplicate a live driver.

    Shared by both create doors (run-session and generic create): it classifies
    the requested launch and runs the two-signal dedup guard, mapping a conflict
    to HTTP 409 naming the holder. A non-driver launch or an unclaimed slug passes
    through silently.
    """
    if not working_slug:
        return
    try:
        await guard_driver_start(
            project_path,
            working_slug,
            launch_class=classify_driver_launch(command),
            caller_session_id=caller_session_id,
        )
    except ClaimConflict as conflict:
        raise HTTPException(status_code=409, detail=conflict.summary()) from conflict


async def guard_generic_create_session(
    request: CreateSessionRequest,
    cmd: object,
    identity: CallerIdentity,
) -> None:
    """Guard the generic ``POST /sessions`` create door against a duplicate driver.

    Resolves the would-be ``working_slug`` from the request the same way the
    create-session primitive does (the "trees/<slug>" worktree subdir, else the
    command's own slug) and runs the shared driver-start guard.
    """
    if not isinstance(cmd, CreateSessionCommand):
        return
    await enforce_driver_start_guard(
        project_path=request.project_path,
        working_slug=resolve_working_slug_from_subdir(request.subdir) or cmd.working_slug,
        command=_leading_command(request.message),
        caller_session_id=identity.session_id,
    )


def _prepare_run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
) -> RunSessionPlan:
    """Normalize run-session inputs into a create-session plan."""
    effective_agent = _resolve_run_session_agent(request)
    normalized_cmd = request.command.lstrip("/")
    normalized_args = request.args.strip()
    full_command = f"/{normalized_cmd} {normalized_args}" if normalized_args else f"/{normalized_cmd}"
    startup_message = _rewrite_codex_next_startup_message(full_command, effective_agent=effective_agent)
    if request.additional_context:
        full_command = f"{full_command}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"
        startup_message = f"{startup_message}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"

    initiator_session_id: str | None = None
    if identity.session_id and not identity.session_id.startswith("web:"):
        initiator_session_id = identity.session_id
    if normalized_cmd in WORKER_LIFECYCLE_COMMANDS:
        if not normalized_args:
            raise HTTPException(status_code=400, detail=f"/{normalized_cmd} requires a slug argument")
    working_slug = _infer_working_slug(normalized_cmd, normalized_args)
    if normalized_cmd in SLUG_REQUIRED_LIFECYCLE_COMMANDS and not working_slug:
        raise HTTPException(status_code=400, detail=f"/{normalized_cmd} requires a slug argument")

    command_domain = _resolve_command_domain_field(normalized_cmd)
    origin_metadata: WebOriginMetadata | None = None
    if identity.email or command_domain:
        origin_metadata = WebOriginMetadata(email=identity.email, command_domain=command_domain)

    try:
        slash_cmd = SlashCommand(normalized_cmd)
    except ValueError:
        slash_cmd = None
    role_info = COMMAND_ROLE_MAP.get(slash_cmd) if slash_cmd else None

    if role_info and identity.system_role:
        target_role = role_info[0]
        allowed = DISPATCH_ALLOWED.get(identity.system_role, frozenset())
        if target_role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"role '{identity.system_role}' cannot dispatch /{normalized_cmd} "
                    f"(requires dispatch privilege for '{target_role}')"
                ),
            )

    return RunSessionPlan(
        effective_agent=effective_agent,
        full_command=full_command,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            agent=effective_agent,
            thinking_mode=request.thinking_mode,
            message=startup_message,
        ),
        initiator_session_id=initiator_session_id,
        origin_metadata=origin_metadata,
        system_role=role_info[0] if role_info else None,
        job=role_info[1].value if role_info else None,
        working_slug=working_slug,
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
        if computer and is_remote_target(computer, config.computer.name):
            await dispatch_session_keys_to_peer(_STATE.client, computer, session_id, request.key, args)
            return {"status": "success"}
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "keys",
            {"session_id": session_id, "key": request.key, "args": args},
            metadata,
        )
        await get_command_service().keys(cmd)
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
    _computer: str | None = Query(None),
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
        )
        await get_command_service().handle_voice(cmd)
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
    _identity: CallerIdentity = Depends(clearance_sessions_agent_restart),
) -> dict[str, str]:
    """Restart agent in session (preserves conversation via --resume)."""
    await check_session_access(http_request, session_id)
    try:
        logger.info("API agent_restart requested (session=%s, origin=api)", session_id)

        # Quick validation before dispatching
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
        )
        asyncio.create_task(get_command_service().restart_agent(cmd), name=f"agent-restart-{session_id}")
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
    identity: CallerIdentity = Depends(clearance_sessions_revive),
) -> CreateSessionResponseDTO:
    """Revive a session by TeleClaude or native session ID."""
    session_id = await _resolve_revive_session_id(http_request, session_id, agent, identity)
    await check_session_access(http_request, session_id)
    try:
        session = await db.get_session(session_id)
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
        )
        success, error = await get_command_service().restart_agent(cmd)
        if not success:
            detail = error or "Failed to revive session"
            raise HTTPException(status_code=409, detail=detail)

        refreshed = await db.get_session(session_id)
        tmux_session_name = refreshed.tmux_session_name if refreshed and refreshed.tmux_session_name else ""
        return CreateSessionResponseDTO(
            status="success",
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            agent=session.active_agent if session.active_agent in get_known_agents() else None,
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
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        messages = _project_session_messages(
            _build_message_chain(session.transcript_files, session.native_log_file),
            active_agent=session.active_agent,
            recipient_email=_identity.email or session.human_email,
            recipient_role=_identity.human_role or session.human_role,
            include_tools=query.include_tools,
            include_thinking=query.include_thinking,
            since=query.since,
        )

        # Fallback path: when transcript files are not yet available or parsing
        # yields no structured entries, use unified session-data retrieval.
        if not messages:
            fallback_payload = await get_command_service().get_session_data(
                GetSessionDataCommand(
                    session_id=session_id,
                    since_timestamp=query.since,
                    tail_chars=query.tail_chars if query.tail_chars > 0 else 10000,
                )
            )
            fallback_text_raw = fallback_payload.get("messages")
            fallback_text = fallback_text_raw if isinstance(fallback_text_raw, str) else ""
            if fallback_text:
                messages = [
                    MessageDTO(
                        role="assistant",
                        type="text",
                        text=fallback_text,
                        timestamp=None,
                        entry_index=0,
                        file_index=0,
                    )
                ]

        messages = _apply_session_tail_scope(messages, query.tail_scope)

        last_activity_at = session.last_activity.isoformat() if isinstance(session.last_activity, datetime) else None
        last_input_at = (
            session.last_message_sent_at.isoformat() if isinstance(session.last_message_sent_at, datetime) else None
        )
        last_agent_stop_at = (
            session.last_agent_stop_at.isoformat() if isinstance(session.last_agent_stop_at, datetime) else None
        )
        agent_status = compute_agent_status(
            lifecycle_status=session.lifecycle_status,
            closed_at=session.closed_at,
            last_activity=session.last_activity,
            last_input_at=session.last_message_sent_at,
            last_agent_stop_at=session.last_agent_stop_at,
        )

        return SessionMessagesDTO(
            session_id=session_id,
            agent=session.active_agent,
            last_activity=last_activity_at,
            last_input_at=last_input_at,
            last_agent_stop_at=last_agent_stop_at,
            agent_status=agent_status,
            messages=messages,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_session_messages failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {e}") from e


# =====================================================================
# Tool CLI endpoints (require dual-factor auth via verify_caller)
# =====================================================================


@router.post("/sessions/run")
async def run_session(
    request: RunSessionRequest,
    identity: CallerIdentity = Depends(clearance_sessions_run),
) -> CreateSessionResponseDTO:
    """Run a slash command on a new agent session.

    Creates a new session with a typed launch intent derived from the given
    slash command, arguments, project, agent, and thinking mode.
    Clearance is enforced by the clearance_sessions_run dependency.
    """
    if not request.command.startswith("/"):
        raise HTTPException(status_code=400, detail="command must start with '/'")
    if not request.project:
        raise HTTPException(status_code=400, detail="project required")

    plan = _prepare_run_session(request, identity)

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
    )
    if isinstance(cmd, CreateSessionCommand):
        cmd.working_slug = plan.working_slug
    await enforce_driver_start_guard(
        project_path=request.project,
        working_slug=plan.working_slug,
        command=request.command,
        caller_session_id=plan.initiator_session_id,
    )
    try:
        data = await get_command_service().create_session(cmd)
        session_id = data.get("session_id")
        tmux_session_name = data.get("tmux_session_name")
        if not session_id or not tmux_session_name:
            raise HTTPException(status_code=500, detail="Failed to create session")
        return CreateSessionResponseDTO(
            status="success",
            session_id=str(session_id),
            tmux_session_name=str(tmux_session_name),
            agent=plan.effective_agent,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("run_session failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run session: {e}") from e


@router.post("/sessions/{session_id}/unsubscribe")
async def unsubscribe_session(
    session_id: str,
    identity: CallerIdentity = Depends(clearance_sessions_unsubscribe),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Stop caring about a target session — umbrella verb across both subscription axes.

    Removes the caller's listener row (if any) AND severs any active direct link
    the caller holds with the target. Idempotent: empty state returns success
    with both action flags false. See `project/spec/session-subscriptions`.
    """
    listener_removed = await unregister_listener(
        target_session_id=session_id,
        caller_session_id=identity.session_id,
    )
    link_id = await close_link_for_member(
        caller_session_id=identity.session_id,
        target_session_id=session_id,
    )
    return {
        "status": "success",
        "listener_removed": listener_removed,
        "link_closed": link_id is not None,
        "link_id": link_id,
    }


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


@router.post("/sessions/self/widget")
async def render_widget_endpoint(
    request: RenderWidgetRequest,
    identity: CallerIdentity = Depends(clearance_sessions_widget),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Render a rich widget expression and send text summary to the session's user.

    Dispatches through CommandService.render_widget() which builds the summary
    and sends through the adapter. Requires dual-factor caller identity.
    """
    cmd = SystemCommand(
        command="render_widget",
        session_id=identity.session_id,
        data={"widget_data": request.data},
    )
    try:
        return await get_command_service().render_widget(cmd)  # type: ignore[return-value]
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
