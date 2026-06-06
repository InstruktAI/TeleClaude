"""Session management command handlers."""

import asyncio
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.config import WORKING_DIR, config
from teleclaude.constants import EVENT_END_SESSION, HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionCloseCompletedPayload, SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.identity import IdentityContext, get_identity_resolver
from teleclaude.core.models import ComputerInfo, MessageMetadata, ProjectInfo, Session, SessionSnapshot
from teleclaude.core.origins import InputOrigin
from teleclaude.core.roadmap import assemble_roadmap_from_db, recently_delivered_cutoff
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX, terminate_session
from teleclaude.core.session_listeners import register_listener
from teleclaude.core.session_title import initial_session_title
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.events.envelope import EventVisibility
from teleclaude.types import CpuStats, DiskStats, MemoryStats, SystemStats
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand, GetSessionDataCommand
from teleclaude.utils import strip_ansi_codes
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

from ._utils import EndSessionHandlerResult, SessionDataPayload, with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


async def create_session(  # noqa: C901 # TODO: refactor to reduce complexity
    cmd: CreateSessionCommand,
    client: "AdapterClient",
) -> dict[str, str]:
    """Create a new tmux session.

    Args:
        cmd: CreateSessionCommand model
        client: AdapterClient

    Returns:
        Minimal session payload with session_id
    """
    del client

    # Get origin from command
    origin = cmd.origin
    if not origin:
        raise ValueError("Command missing origin")

    logger.info(
        "CreateSession: origin=%s launch_intent=%s",
        origin,
        cmd.launch_intent.kind.value if cmd.launch_intent else None,
    )

    computer_name = config.computer.name
    session_id = cmd.session_id or str(uuid.uuid4())
    tmux_name = "" if cmd.headless else f"{TMUX_SESSION_PREFIX}{session_id}"

    subfolder = cmd.subdir
    working_slug: str | None = None
    if subfolder and subfolder.startswith("trees/"):
        working_slug = subfolder.removeprefix("trees/")
    initiator_session_id = cmd.initiator_session_id
    cmd_system_role = cmd.system_role
    cmd_job = cmd.job

    # Origin provenance must reflect the actual source of this session creation.
    # Do not inherit origin from parent sessions.
    last_input_origin = origin
    parent_session = None
    if initiator_session_id:
        parent_session = await db.get_session(initiator_session_id)

    # Resolve identity from typed origin metadata when available.
    # Sessions without origin_metadata (e.g. telegram before adapter conversion)
    # proceed with no identity — parent inheritance or role-based access applies.
    identity: IdentityContext | None = None
    human_email: str | None = cmd.human_email
    human_role: str | None = cmd.human_role
    if cmd.origin_metadata:
        identity = get_identity_resolver().resolve(origin, cmd.origin_metadata)
        if not human_email:
            human_email = identity.person_email
        if not human_role:
            human_role = identity.person_role

    # Handle parent session identity inheritance
    principal: str | None = None
    if parent_session:
        if not human_email and parent_session.human_email:
            human_email = parent_session.human_email
        if not human_role and parent_session.human_role:
            human_role = parent_session.human_role
        if not principal and parent_session.principal:
            principal = parent_session.principal

    if not human_role and not cmd_system_role:
        raise ValueError(f"Session creation failed: no identity resolved and no system_role (origin={origin})")

    # System-role sessions (workers, orchestrators, integrators) are trusted
    # internal principals — they bypass help-desk routing entirely.
    system_role = cmd_system_role
    raw_help_desk_path = getattr(config.computer, "help_desk_dir", None)
    configured_help_desk_path = (
        raw_help_desk_path
        if isinstance(raw_help_desk_path, str) and raw_help_desk_path.strip()
        else os.path.join(WORKING_DIR, "help-desk")
    )
    if not system_role and human_role and human_role not in (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER):
        logger.info(
            "Restricted session attempt from origin=%s role=%s. Jailing to help-desk.",
            origin,
            human_role,
        )
        project_path = configured_help_desk_path
        Path(project_path).mkdir(parents=True, exist_ok=True)
        subfolder = None
        working_slug = None
    else:
        project_path = cmd.project_path
        if not project_path:
            logger.info(
                "Session creation missing project_path from origin=%s; defaulting to help-desk.",
                origin,
            )
            project_path = configured_help_desk_path
            Path(project_path).mkdir(parents=True, exist_ok=True)
            subfolder = None
            working_slug = None
    project_path = os.path.expanduser(os.path.expandvars(project_path))

    # tmux silently falls back to its own cwd if -c points at a non-existent directory.
    # This shows up as sessions "starting in /tmp" (or similar) even though we asked for a project dir.
    working_dir = resolve_working_dir(project_path, subfolder)
    working_dir_path = Path(working_dir)
    if not working_dir_path.is_absolute():
        raise ValueError(f"Working directory must be an absolute path: {working_dir}")
    if not working_dir_path.exists():
        raise ValueError(f"Working directory does not exist: {working_dir}")
    if not working_dir_path.is_dir():
        raise ValueError(f"Working directory is not a directory: {working_dir}")
    working_dir = str(working_dir_path)

    if subfolder:
        if Path(subfolder).is_absolute():
            raise ValueError(f"subdir must be relative: {subfolder}")
        subfolder = subfolder.strip("/")

    # Derive working_dir from raw inputs (project_path + subfolder)
    # project_path is the base project, subfolder is the optional worktree/branch path
    if subfolder:
        working_dir = resolve_working_dir(project_path, subfolder)
        working_dir_path = Path(working_dir)
        if not working_dir_path.exists():
            working_dir_path.mkdir(parents=True, exist_ok=True)
        working_dir = str(working_dir_path)

    title = initial_session_title(cmd.initial_input)

    # Create session atomically with all known fields — the SESSION_STARTED
    # event must carry complete data so downstream consumers never see partial state.
    launch = cmd.launch_intent
    session = await db.create_session(
        computer_name=computer_name,
        tmux_session_name=tmux_name,
        last_input_origin=last_input_origin,
        title=title,
        project_path=project_path,
        subdir=subfolder,
        session_id=session_id,
        working_slug=working_slug,
        initiator_session_id=initiator_session_id,
        detached=cmd.skip_listener_registration,
        human_email=human_email,
        human_role=human_role,
        principal=principal,
        lifecycle_status="headless" if cmd.headless else "initializing",
        system_role=cmd_system_role,
        job=cmd_job,
        active_agent=launch.agent if launch else None,
        thinking_mode=launch.thinking_mode if launch else None,
        native_session_id=cmd.native_session_id or (launch.native_session_id if launch else None),
        native_log_file=cmd.native_log_file,
        emit_session_started=False,
    )

    # AI-to-AI starts should register a one-shot stop listener so the initiator
    # receives completion notifications for the spawned child session.
    if initiator_session_id and initiator_session_id != session_id and not cmd.skip_listener_registration:
        caller_tmux = parent_session.tmux_session_name if parent_session else None
        if caller_tmux:
            try:
                await register_listener(
                    target_session_id=session_id,
                    caller_session_id=initiator_session_id,
                    caller_tmux_session=caller_tmux,
                )
            except RuntimeError:
                logger.debug(
                    "Listener registration skipped (db unavailable): caller=%s target=%s",
                    initiator_session_id,
                    session_id,
                )
            except Exception as exc:
                logger.warning(
                    "Listener registration failed: caller=%s target=%s error=%s",
                    initiator_session_id,
                    session_id,
                    exc,
                )
        else:
            logger.debug(
                "Listener registration skipped: initiator missing or has no tmux session (caller=%s target=%s)",
                initiator_session_id,
                session_id,
            )
    elif initiator_session_id and initiator_session_id != session_id and cmd.skip_listener_registration:
        logger.debug(
            "Listener registration skipped by command flag (caller=%s target=%s)",
            initiator_session_id,
            session_id,
        )

    # Merge typed origin metadata into session's origin_metadata
    if cmd.origin_metadata:
        await db.update_origin_metadata(session.session_id, last_input_origin, dict(cmd.origin_metadata))

    # NOTE: tmux creation + launch execution are handled asynchronously
    # by the daemon bootstrap task. Channel creation is deferred to UI lanes
    # on first output.

    logger.info("Created session: %s (headless=%s)", session.session_id, cmd.headless)
    return {"session_id": session_id, "tmux_session_name": tmux_name}


async def list_sessions(*, include_closed: bool = False) -> list[SessionSnapshot]:
    """List sessions from local database.

    Ephemeral request/response for tool/API callers only - no DB session required.
    UI adapters (Telegram) should not have access to this command.
    """
    sessions = await db.list_sessions(include_headless=True, include_closed=include_closed)

    local_name = config.computer.name
    snapshots = [SessionSnapshot.from_db_session(session, computer=local_name) for session in sessions]
    for snapshot in snapshots:
        if not snapshot.thinking_mode:
            snapshot.thinking_mode = "slow"
        if not snapshot.status:
            snapshot.status = "active"
    return snapshots


async def list_projects() -> list[ProjectInfo]:
    """List trusted project directories.

    Ephemeral request/response - no DB session required.

    Returns:
        List of project info objects.
    """
    # Get all trusted dirs (includes default_working_dir merged in)
    all_trusted_dirs = config.computer.get_all_trusted_dirs()

    # Build structured response with name, desc, path
    # Filter to only existing directories
    dirs_data = []
    for trusted_dir in all_trusted_dirs:
        expanded_path = os.path.expanduser(os.path.expandvars(trusted_dir.path))
        if Path(expanded_path).exists():
            dirs_data.append(
                ProjectInfo(
                    name=trusted_dir.name,
                    description=trusted_dir.desc,
                    path=expanded_path,
                )
            )

    return dirs_data


async def list_projects_with_todos() -> list[ProjectInfo]:
    """List projects with their todos included (local only)."""
    raw_projects = await list_projects()
    projects_with_todos: list[ProjectInfo] = []

    for project in raw_projects:
        todos: list[TodoDTO] = []
        if project.path:
            todos = await list_todos(project.path)

        project.todos = todos
        projects_with_todos.append(project)

    return projects_with_todos


async def list_todos(project_path: str) -> list[TodoDTO]:
    """List todos for a project.

    Ephemeral request/response - no DB session required.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of todo objects.
    """
    return assemble_roadmap_from_db(
        project_path,
        include_icebox=True,
        include_delivered=True,
        delivered_since=recently_delivered_cutoff(),
        include_removed=True,
    )


async def get_computer_info() -> ComputerInfo:
    """Return computer info including system stats.

    Ephemeral request/response - no DB session required.

    Returns:
        ComputerInfo object.
    """
    logger.debug("get_computer_info() called")

    # Build info from config - design by contract: these fields are required
    if not config.computer.user or not config.computer.role or not config.computer.host:
        raise ValueError("Computer configuration is incomplete - user, role, and host are required")

    # Gather system stats (parallel, non-blocking cpu_percent)
    memory, disk, cpu_percent = await asyncio.gather(
        asyncio.to_thread(psutil.virtual_memory),
        asyncio.to_thread(psutil.disk_usage, "/"),
        asyncio.to_thread(psutil.cpu_percent, None),
    )

    # Build typed system stats
    memory_stats: MemoryStats = {
        "total_gb": round(memory.total / (1024**3), 1),
        "available_gb": round(memory.available / (1024**3), 1),
        "percent_used": memory.percent,
    }
    disk_stats: DiskStats = {
        "total_gb": round(disk.total / (1024**3), 1),
        "free_gb": round(disk.free / (1024**3), 1),
        "percent_used": disk.percent,
    }
    cpu_stats: CpuStats = {
        "percent_used": cpu_percent,
    }
    system_stats: SystemStats = {
        "memory": memory_stats,
        "disk": disk_stats,
        "cpu": cpu_stats,
    }

    info = ComputerInfo(
        name=config.computer.name,
        status="online",
        user=config.computer.user,
        role=config.computer.role,
        host=config.computer.host,
        is_local=True,
        system_stats=system_stats,
    )

    logger.debug("get_computer_info() returning info: %s", info)
    return info


async def get_session_data(
    cmd: GetSessionDataCommand,
) -> SessionDataPayload:
    """Get session data from native_log_file.

    Reads the Agent session file (JSONL format) and parses to markdown.
    Uses same parsing as download functionality for consistent formatting.
    Supports timestamp filtering and character limit.

    Args:
        cmd: GetSessionDataCommand payload

    Returns:
        Dict with session data and markdown-formatted messages
    """

    # Get session from database
    session_id = cmd.session_id
    session = await db.get_session(session_id)
    if not session:
        logger.error("Session %s not found", session_id)
        return {"status": "error", "error": "Session not found"}

    def _pending_transcript_payload(reason: str) -> SessionDataPayload:
        logger.debug(
            "Transcript pending for session %s (%s)",
            session_id,
            reason,
        )
        agent_label = str(session.active_agent or "session")
        return {
            "status": "success",
            "session_id": session_id,
            "project_path": session.project_path,
            "subdir": session.subdir,
            "messages": (
                f"Transcript is not available yet for this {agent_label} session. "
                "Wait for the first completed turn (`agent_stop`) and retry."
            ),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
            "transcript": None,
        }

    async def _tmux_fallback_payload(reason: str) -> SessionDataPayload | None:
        tmux_session_name = getattr(session, "tmux_session_name", None)
        if not isinstance(tmux_session_name, str) or not tmux_session_name.strip():
            return None

        tail = cmd.tail_chars if cmd.tail_chars > 0 else 2000
        try:
            pane_output = await tmux_bridge.capture_pane(
                tmux_session_name,
                capture_lines=tmux_bridge.FALLBACK_CAPTURE_LINES,
            )
        except (OSError, ValueError, tmux_bridge.SubprocessTimeoutError) as exc:
            logger.warning(
                "Tmux fallback capture failed for session %s (%s): %s",
                session_id,
                reason,
                exc,
            )
            return None

        # Strip ANSI before truncation so tail slicing cannot split escape codes.
        sanitized_output = strip_ansi_codes(pane_output)
        messages = sanitized_output[-tail:] if len(sanitized_output) > tail else sanitized_output
        logger.debug(
            "Returning tmux fallback output for session %s (%s)",
            session_id,
            reason,
        )
        return {
            "status": "success",
            "session_id": session_id,
            "project_path": session.project_path,
            "subdir": session.subdir,
            "messages": messages,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
        }

    raw_agent_name = session.active_agent or ""
    normalized_agent_name = raw_agent_name.strip().lower()
    lifecycle_status = session.lifecycle_status or ""
    closed_at_raw = session.closed_at
    session_closed = closed_at_raw is not None or lifecycle_status == "closed"
    feedback_at_raw = session.last_output_at
    has_completed_turn = feedback_at_raw is not None

    # Get native_log_file from session, or discover it if not set
    native_log_file_str = session.native_log_file

    # For Codex sessions, try to discover transcript if not yet bound
    if not native_log_file_str and normalized_agent_name == "codex" and session.native_session_id:
        logger.debug(
            "Attempting to discover Codex transcript for session %s (native_id=%s)",
            session_id,
            session.native_session_id,
        )
        discovered_path = discover_codex_transcript_path(session.native_session_id)
        if discovered_path:
            native_log_file_str = discovered_path
            logger.info(
                "Discovered Codex transcript path for session %s: %s",
                session_id,
                discovered_path,
            )
            # Update database for future queries
            await db.update_session(session_id, native_log_file=discovered_path)

    if not native_log_file_str:
        tmux_payload = await _tmux_fallback_payload("no_native_log_file")
        if tmux_payload:
            return tmux_payload
        if normalized_agent_name == "codex":
            return _pending_transcript_payload("no_native_log_file_codex")
        if not has_completed_turn and not session_closed:
            return _pending_transcript_payload("no_native_log_file_pre_stop")
        logger.error("No native_log_file for session %s", session_id)
        return {"status": "error", "error": "Session file not found"}

    native_log_file = Path(native_log_file_str)
    if not native_log_file.exists():
        tmux_payload = await _tmux_fallback_payload("native_log_file_missing")
        if tmux_payload:
            return tmux_payload
        if normalized_agent_name == "codex":
            return _pending_transcript_payload("native_log_file_missing_on_disk_codex")
        if not has_completed_turn and not session_closed:
            return _pending_transcript_payload("native_log_file_missing_pre_stop")
        logger.error("Native session file does not exist: %s", native_log_file)
        return {"status": "error", "error": "Session file does not exist"}

    if not raw_agent_name:
        logger.error("Session %s missing active_agent metadata", session_id)
        return {"status": "error", "error": "Active agent unknown"}

    try:
        agent_name = AgentName.from_str(raw_agent_name)
    except ValueError as exc:
        logger.error("Unknown agent for session %s: %s", session_id, exc)
        return {"status": "error", "error": str(exc)}

    parser_info = get_transcript_parser_info(agent_name)

    # Parse session transcript to markdown with filtering
    try:
        markdown_content = parse_session_transcript(
            str(native_log_file),
            session.title,
            agent_name=agent_name,
            since_timestamp=cmd.since_timestamp,
            until_timestamp=cmd.until_timestamp,
            tail_chars=cmd.tail_chars if cmd.tail_chars > 0 else 2000,
        )
        logger.info(
            "Parsed %s transcript (%d bytes) for session %s",
            parser_info.display_name,
            len(markdown_content),
            session_id,
        )
    except Exception as e:
        logger.error("Failed to parse session file %s: %s", native_log_file, e)
        return {"status": "error", "error": f"Failed to parse session file: {e}"}

    return {
        "status": "success",
        "session_id": session_id,
        "project_path": session.project_path,
        "subdir": session.subdir,
        "messages": markdown_content,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
    }


@with_session
async def close_session(
    session: Session,
    _cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> None:
    """Close session - kill tmux, delete DB record, clean up resources.

    Routing: when the stored computer_name names a different host, the command is
    forwarded to that remote peer — but only if the session is not actually present
    locally. A live local tmux session means it is local (computer_name may have
    drifted via a host/config rename), so it is closed here regardless of the name.
    """
    # Route to a remote peer only when the stored name says remote AND the session is
    # not actually present on this host. computer_name is frozen at creation and can
    # drift (host rename / config-name correction), so trusting it alone would forward a
    # locally-running session to a phantom peer and leave it un-closable. Local tmux
    # presence is the ground truth for locality.
    local_computer = config.computer.name
    if session.computer_name and session.computer_name != local_computer:
        # Stored name says remote — but verify against ground truth before forwarding.
        # computer_name is frozen at creation and can drift (host rename / config-name
        # correction); forwarding a locally-running session to a phantom peer leaves it
        # un-closable. A live local tmux session means it is local, regardless of the name.
        locally_present = bool(session.tmux_session_name) and await tmux_bridge.session_exists(
            session.tmux_session_name, log_missing=False
        )
        if not locally_present:
            logger.info(
                "Forwarding close_session to remote computer %s for session %s",
                session.computer_name,
                session.session_id,
            )
            await client.dispatch_remote_command(
                target_computer=session.computer_name,
                command=EVENT_END_SESSION,
                metadata=MessageMetadata(origin=InputOrigin.TERMINAL.value),
                session_id=session.session_id,
                wait_for_response=False,
            )
            return

    # closed_at is the sole "finalized" signal. A session marked only
    # lifecycle_status="closing" with no closed_at is a stuck/in-flight close — NOT
    # terminal. It must fall through to terminate_session so closed_at actually gets
    # set; otherwise the row is hidden but never finalized and resurfaces from caches.
    if session.closed_at or session.lifecycle_status == "closed":
        logger.info("Session %s already terminal; replaying close_completed", session.session_id)
        event_bus.emit(
            _cmd.completion_event,  # type: ignore[arg-type]
            SessionCloseCompletedPayload(session_id=session.session_id),
            visibility=EventVisibility.CLUSTER,
        )
        return

    await terminate_session(
        session.session_id,
        client,
        reason="close_session",
        session=session,
    )
    event_bus.emit(
        _cmd.completion_event,  # type: ignore[arg-type]
        SessionCloseCompletedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )


async def end_session(
    cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> EndSessionHandlerResult:
    """End a session via tool/API request.

    Similar to close_session but designed for direct command calls.
    Kills tmux, deletes the session, cleans up resources.

    Args:
        session_id: Session identifier
        client: AdapterClient for channel operations

    Returns:
        dict with status and message
    """
    # Get session from DB
    session = await db.get_session(cmd.session_id)
    if not session:
        return {"status": "error", "message": f"Session {cmd.session_id} not found"}

    # closed_at is the sole "finalized" signal. A session marked only
    # lifecycle_status="closing" with no closed_at is a stuck/in-flight close
    # (e.g. a prior close interrupted before finalize) — NOT terminal. It must
    # fall through to terminate_session so closed_at actually gets set; otherwise
    # the row is hidden but never finalized and resurfaces from cached snapshots.
    if session.closed_at or session.lifecycle_status == "closed":
        logger.info("Session %s already terminal; replaying session_closed", cmd.session_id)
        event_bus.emit(
            TeleClaudeEvents.SESSION_CLOSED,
            SessionLifecycleContext(session_id=session.session_id),
            visibility=EventVisibility.CLUSTER,
        )
        return {
            "status": "success",
            "message": f"Session {cmd.session_id} already closed; session_closed replayed",
        }

    terminated = await terminate_session(
        cmd.session_id,
        client,
        reason="end_session",
        session=session,
        delete_db=False,
    )
    if not terminated:
        # The session exists (fetched above); terminate_session returns False only
        # when a close is already in flight — benign, that close will finalize.
        return {"status": "success", "message": f"Session {cmd.session_id} close already in progress"}

    return {
        "status": "success",
        "message": f"Session {cmd.session_id} ended successfully",
    }
