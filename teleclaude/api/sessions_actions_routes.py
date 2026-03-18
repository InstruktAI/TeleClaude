"""Session action endpoints (keys, voice, file, revive, run, result, widget, escalate)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import shlex
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord_adapter import DiscordAdapter
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
from teleclaude.api_models import (
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
from teleclaude.api.session_access import check_session_access
from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, SlashCommand
from teleclaude.core.agents import (
    assert_agent_enabled,
    get_default_agent,
    get_known_agents,
    resolve_parser_agent,
)
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.command_service import COMMAND_ROLE_MAP
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, SessionMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import unregister_listener
from teleclaude.core.session_utils import get_short_project_name, split_project_path_and_subdir
from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import VisibilityPolicy
from teleclaude.output_projection.serializers import to_structured_message
from teleclaude.types.commands import GetSessionDataCommand
from teleclaude.utils.markdown import telegramify_markdown

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

WORKER_LIFECYCLE_COMMANDS = {
    SlashCommand.NEXT_BUILD,
    SlashCommand.NEXT_REVIEW_BUILD,
    SlashCommand.NEXT_FIX_REVIEW,
    SlashCommand.NEXT_FINALIZE,
}

_STATE = SimpleNamespace(client=None)

router = APIRouter()


def configure(client: AdapterClient | None = None) -> None:
    """Wire client; called from APIServer at construction."""
    if client is not None:
        _STATE.client = client


def _build_metadata(**kwargs: object) -> MessageMetadata:
    """Build API boundary metadata."""
    return MessageMetadata(origin=InputOrigin.API.value, **kwargs)


@dataclass(frozen=True)
class SessionMessagesQuery:
    """Normalized query parameters for message retrieval."""

    since: str | None = None
    include_tools: bool = False
    include_thinking: bool = False
    tail_chars: int = 10000


def _parse_session_messages_query(
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; only messages after this time"),
    include_tools: bool = Query(False, description="Include tool_use/tool_result entries"),
    include_thinking: bool = Query(False, description="Include thinking/reasoning blocks"),
    tail_chars: int = Query(10000, description="Fallback char budget for tmux/session tail output"),
) -> SessionMessagesQuery:
    """Collect session-messages query parameters into one object."""
    return SessionMessagesQuery(
        since=since,
        include_tools=include_tools,
        include_thinking=include_thinking,
        tail_chars=tail_chars,
    )


async def _resolve_revive_session_id(
    http_request: Request,
    session_id: str,
    agent: str | None,
    identity: CallerIdentity,
) -> str:
    """Resolve a TeleClaude session id for revive requests."""
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

    new_session_id = str(uuid.uuid4())
    project_path: str | None = None
    subdir: str | None = None
    title = "Revived"
    raw_project = http_request.query_params.get("project")
    if raw_project:
        trusted_dirs = [trusted_dir.path for trusted_dir in config.computer.get_all_trusted_dirs()]
        project_path, subdir = split_project_path_and_subdir(raw_project, trusted_dirs)
        if project_path:
            title = get_short_project_name(project_path, subdir)

    await db.create_headless_session(
        session_id=new_session_id,
        computer_name=config.computer.name,
        last_input_origin=InputOrigin.TERMINAL.value,
        title=title,
        active_agent=agent,
        native_session_id=session_id,
        native_log_file=None,
        project_path=project_path,
        subdir=subdir,
        human_role=identity.human_role or HUMAN_ROLE_CUSTOMER,
    )
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
    include_tools: bool,
    include_thinking: bool,
    since: str | None,
) -> list[MessageDTO]:
    """Project transcript files into structured messages."""
    if not chain:
        return []

    projected_blocks = project_conversation_chain(
        chain,
        resolve_parser_agent(active_agent),
        VisibilityPolicy(
            include_tools=include_tools,
            include_tool_results=include_tools,
            include_thinking=include_thinking,
        ),
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
        for message in (to_structured_message(projected_block) for projected_block in projected_blocks)
    ]


@dataclass(frozen=True)
class RunSessionPlan:
    """Normalized data needed to create a run-session request."""

    effective_agent: str
    full_command: str
    auto_command: str
    channel_metadata: dict[str, str] | None
    session_meta: SessionMetadata


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


def _prepare_run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
) -> RunSessionPlan:
    """Normalize run-session inputs into a create-session plan."""
    effective_agent = _resolve_run_session_agent(request)
    normalized_cmd = request.command.lstrip("/")
    normalized_args = request.args.strip()
    full_command = f"/{normalized_cmd} {normalized_args}" if normalized_args else f"/{normalized_cmd}"
    if request.additional_context:
        full_command = f"{full_command}\n\nADDITIONAL CONTEXT:\n{request.additional_context}"
    auto_command = f"agent_then_message {effective_agent} {request.thinking_mode} {shlex.quote(full_command)}"

    channel_metadata: dict[str, str] | None = None
    if identity.session_id and not identity.session_id.startswith("web:"):
        channel_metadata = {"initiator_session_id": identity.session_id}
    if normalized_cmd in WORKER_LIFECYCLE_COMMANDS:
        if not normalized_args:
            raise HTTPException(status_code=400, detail=f"/{normalized_cmd} requires a slug argument")
        channel_metadata = channel_metadata or {}
        channel_metadata["working_slug"] = normalized_args.split()[0]

    try:
        slash_cmd = SlashCommand(normalized_cmd)
    except ValueError:
        slash_cmd = None
    role_info = COMMAND_ROLE_MAP.get(slash_cmd) if slash_cmd else None
    session_meta = SessionMetadata(
        system_role=role_info[0] if role_info else None,
        job=role_info[1].value if role_info else None,
        human_role=identity.human_role,
        principal=identity.principal,
    )
    return RunSessionPlan(
        effective_agent=effective_agent,
        full_command=full_command,
        auto_command=auto_command,
        channel_metadata=channel_metadata,
        session_meta=session_meta,
    )


def _build_widget_summary(data: dict[str, object]) -> str:
    """Build the text summary sent for a rich widget payload."""
    title = str(data.get("title", ""))
    sections = data.get("sections", [])
    footer = str(data.get("footer", ""))
    if not isinstance(sections, list):
        raise HTTPException(status_code=400, detail="sections must be an array")

    summary_parts: list[str] = [f"**{title}**\n"] if title else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = section.get("label")
        if label:
            summary_parts.append(f"_{label}_")

        section_type = str(section.get("type", ""))
        if section_type == "text":
            content = str(section.get("content", ""))
            if content:
                summary_parts.append(content)
            continue
        if section_type == "table":
            headers = section.get("headers", [])
            rows = section.get("rows", [])
            if isinstance(headers, list) and isinstance(rows, list):
                summary_parts.append(f"Table: {len(headers)} columns, {len(rows)} rows")
            continue
        if section_type == "code":
            lang = str(section.get("language", ""))
            content = str(section.get("content", ""))
            lang_label = f" ({lang})" if lang else ""
            preview = content[:100] + "..." if len(content) > 100 else content
            summary_parts.append(f"Code{lang_label}:\n```\n{preview}\n```")
            continue
        if section_type == "divider":
            summary_parts.append("---")

    if footer:
        summary_parts.append(f"\n{footer}")
    return "\n".join(summary_parts)


@router.post("/sessions/{session_id}/keys")
async def send_keys_endpoint(
    http_request: Request,
    session_id: str,
    request: KeysRequest,
    _computer: str | None = Query(None),
    _identity: CallerIdentity = Depends(clearance_sessions_keys),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send key command to session."""
    await check_session_access(http_request, session_id)
    try:
        metadata = _build_metadata()
        args: list[str] = []
        if request.count:
            args = [str(request.count)]
        cmd = CommandMapper.map_api_input(
            "keys",
            {"session_id": session_id, "key": request.key, "args": args},
            metadata,
        )
        await get_command_service().keys(cmd)
        return {"status": "success"}
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
    """Send file input to session."""
    session_id = identity.session_id
    try:
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "handle_file",
            {
                "session_id": session_id,
                "file_path": request.file_path,
                "filename": request.filename,
                "caption": request.caption,
                "file_size": request.file_size,
            },
            metadata,
        )
        await get_command_service().handle_file(cmd)
        return {"status": "success"}
    except Exception as e:
        logger.error("send_file failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send file: {e}") from e


@router.post("/sessions/{session_id}/agent-restart")
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
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "agent_restart",
            {"session_id": session_id, "args": []},
            metadata,
        )
        asyncio.create_task(get_command_service().restart_agent(cmd))
        return {"status": "accepted"}
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

        return SessionMessagesDTO(
            session_id=session_id,
            agent=session.active_agent,
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

    Creates a new session with an auto_command derived from the given
    slash command, arguments, project, agent, and thinking mode.
    Requires dual-factor caller identity (X-Caller-Session-Id + X-Tmux-Session).
    """
    if not identity.session_id:
        raise HTTPException(
            status_code=400,
            detail="sessions/run requires caller session identity",
        )
    if not request.command.startswith("/"):
        raise HTTPException(status_code=400, detail="command must start with '/'")
    if not request.project:
        raise HTTPException(status_code=400, detail="project required")

    plan = _prepare_run_session(request, identity)

    metadata = _build_metadata(
        title=plan.full_command,
        project_path=request.project,
        subdir=request.subfolder or None,
        channel_metadata=plan.channel_metadata,
        session_metadata=plan.session_meta,
    )
    metadata.auto_command = plan.auto_command

    cmd = CommandMapper.map_api_input(
        "new_session",
        {"skip_listener_registration": request.detach},
        metadata,
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
    """Stop receiving notifications from a session without ending it.

    Unregisters the caller's listener for the target session. The session
    continues running but the caller no longer receives events from it.
    Requires dual-factor caller identity.
    """
    success = await unregister_listener(target_session_id=session_id, caller_session_id=identity.session_id)
    if success:
        return {"status": "success", "message": f"Stopped notifications from session {session_id}"}
    return {"status": "error", "message": f"No listener found for session {session_id}"}


@router.post("/sessions/self/result")
async def send_result_endpoint(
    request: SendResultRequest,
    identity: CallerIdentity = Depends(clearance_sessions_result),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send a formatted result to the session's user as a separate message.

    Sends the content through the session's adapter (Telegram, Discord, etc.)
    as a persistent (non-ephemeral) message. Supports markdown and HTML formats.
    Requires dual-factor caller identity.
    """
    if _STATE.client is None:
        raise HTTPException(status_code=503, detail="Adapter client not available")

    session = await db.get_session(identity.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.output_format == "html":
        formatted_content = request.content
        parse_mode = "HTML"
    else:
        formatted_content = telegramify_markdown(request.content)
        parse_mode = "MarkdownV2"

    if len(formatted_content) > 4096:
        formatted_content = formatted_content[:4090] + "\n..."

    meta = MessageMetadata(parse_mode=parse_mode)
    try:
        message_id = await _STATE.client.send_message(
            session=session,
            text=formatted_content,
            metadata=meta,
            ephemeral=False,
        )
        return {"status": "success", "message_id": message_id}
    except (AdapterError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("send_result formatted send failed, retrying as plain text: %s", e)
        try:
            message_id = await _STATE.client.send_message(
                session=session,
                text=request.content[:4096],
                metadata=MessageMetadata(),
                ephemeral=False,
            )
            return {
                "status": "success",
                "message_id": message_id,
                "warning": "Sent as plain text due to formatting error",
            }
        except (AdapterError, RuntimeError, ValueError, TypeError) as fallback_error:
            raise HTTPException(status_code=500, detail=f"Failed to send result: {fallback_error}") from fallback_error


@router.post("/sessions/self/widget")
async def render_widget_endpoint(
    request: RenderWidgetRequest,
    identity: CallerIdentity = Depends(clearance_sessions_widget),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Render a rich widget expression and send text summary to the session's user.

    Generates a text summary from the widget sections, sends it through the
    session's adapter, and stores named widgets for retrieval. Requires
    dual-factor caller identity.
    """
    if _STATE.client is None:
        raise HTTPException(status_code=503, detail="Adapter client not available")

    session = await db.get_session(identity.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    text_summary = _build_widget_summary(request.data)
    meta = MessageMetadata(parse_mode="MarkdownV2")
    try:
        await _STATE.client.send_message(
            session=session,
            text=telegramify_markdown(text_summary),
            metadata=meta,
            ephemeral=False,
        )
    except Exception as e:
        logger.error("render_widget send failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send widget: {e}") from e

    return {"status": "success", "summary": text_summary}


@router.post("/sessions/self/escalate")
async def escalate_session(
    request: EscalateRequest,
    identity: CallerIdentity = Depends(clearance_sessions_escalate),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Escalate a customer session to an admin via Discord.

    Creates a Discord thread in the escalation forum, notifies admins,
    and activates relay mode on the session. Only available for customer
    sessions. Requires dual-factor caller identity.
    """
    if _STATE.client is None:
        raise HTTPException(status_code=503, detail="Adapter client not available")

    session_id = identity.session_id
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.human_role != "customer":
        raise HTTPException(status_code=403, detail="Escalation is only available in customer sessions")

    discord_adapter: DiscordAdapter | None = None
    for adapter in _STATE.client.adapters.values():
        if isinstance(adapter, DiscordAdapter):
            discord_adapter = adapter
            break
    if not discord_adapter:
        raise HTTPException(status_code=503, detail="Discord adapter not available")

    try:
        thread_id = await discord_adapter.create_escalation_thread(
            customer_name=request.customer_name,
            reason=request.reason,
            context_summary=request.context_summary,
            session_id=session_id,
        )
        now = datetime.now(UTC)
        await db.update_session(
            session_id,
            relay_status="active",
            relay_discord_channel_id=str(thread_id),
            relay_started_at=now.isoformat(),
        )
        return {"status": "success", "thread_id": thread_id}
    except Exception as e:
        logger.error("escalate_session failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Escalation failed: {e}") from e
