"""Command handlers for TeleClaude bot commands.

Extracted from daemon.py to reduce file size and improve organization.
All handlers are stateless functions with explicit dependencies.
"""

import asyncio
import functools
import os
import re
import shlex
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional, TypedDict, cast

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agents import AgentName, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.models import (
    AgentResumeArgs,
    AgentStartArgs,
    ComputerInfo,
    MessageMetadata,
    ProjectInfo,
    Session,
    SessionSummary,
    ThinkingMode,
    TodoInfo,
)
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX, cleanup_session_resources, terminate_session
from teleclaude.core.session_utils import (
    build_session_title,
    ensure_unique_title,
    get_short_project_name,
    resolve_working_dir,
    update_title_with_agent,
)
from teleclaude.core.voice_assignment import get_random_voice, get_voice_env_vars
from teleclaude.types import CpuStats, DiskStats, MemoryStats, SystemStats
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    KeysCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    SendMessageCommand,
    StartAgentCommand,
)
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

logger = get_logger(__name__)


# Result from end_session
class EndSessionHandlerResult(TypedDict):
    """Result from end_session."""

    status: str
    message: str


# Session data payload returned by get_session_data
class SessionDataPayload(TypedDict, total=False):
    """Session data payload returned by get_session_data."""

    status: str  # Required - always present
    session_id: str
    transcript: str | None
    last_activity: str | None
    project_path: str | None
    subdir: str | None
    error: str  # Present in error responses
    messages: str  # Sometimes present
    created_at: str | None  # Sometimes present


# Type alias for start_polling function
StartPollingFunc = Callable[[str, str], Awaitable[None]]


# Decorator to inject session from context (removes boilerplate)
def with_session(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator that extracts and injects session from a command object."""

    @functools.wraps(func)
    async def wrapper(cmd: object, *args: object, **kwargs: object) -> None:
        if not hasattr(cmd, "session_id"):
            raise ValueError(f"Object {type(cmd).__name__} missing session_id")

        session_id = str(getattr(cmd, "session_id"))
        session = await db.get_session(session_id)
        if session is None:
            raise RuntimeError(f"Session {session_id} not found - this should not happen")

        await func(session, cmd, *args, **kwargs)

    return wrapper


async def _execute_control_key(
    tmux_action: Callable[..., Awaitable[bool]],
    session: Session,
    *tmux_args: object,
) -> bool:
    """Execute control/navigation key without polling (TUI interaction).

    Used for keys that interact with TUIs and don't produce shell output:
    arrow keys, tab, shift+tab, escape, ctrl, cancel, kill.

    Args:
        tmux_action: Tmux bridge function to execute
        session: Session object (contains tmux_session_name)
        *tmux_args: Additional arguments for tmux_action

    Returns:
        True if tmux action succeeded, False otherwise
    """
    return await tmux_action(session, *tmux_args)


async def create_session(  # pylint: disable=too-many-locals  # Session creation requires many variables
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
    # Get origin from command
    origin = cmd.origin
    if not origin:
        raise ValueError("Command missing origin")

    computer_name = config.computer.name
    # Generate tmux session name with prefix for TeleClaude ownership
    session_id = str(uuid.uuid4())
    tmux_name = f"{TMUX_SESSION_PREFIX}{session_id[:8]}"

    # Extract metadata from channel_metadata if present (AI-to-AI session)
    initiator = None
    initiator_agent = None
    initiator_mode = None
    subfolder = cmd.subdir
    working_slug = cmd.working_slug
    initiator_session_id = cmd.initiator_session_id

    if cmd.channel_metadata:
        initiator_raw = cmd.channel_metadata.get("target_computer")
        initiator = str(initiator_raw) if initiator_raw else None
        initiator_agent_raw = cmd.channel_metadata.get("initiator_agent")
        initiator_agent = str(initiator_agent_raw) if initiator_agent_raw else None
        initiator_mode_raw = cmd.channel_metadata.get("initiator_mode")
        initiator_mode = str(initiator_mode_raw) if initiator_mode_raw else None
        # subfolder/slug/initiator_id can also be in metadata, but command fields take precedence
        subfolder = subfolder or cast(Optional[str], cmd.channel_metadata.get("subfolder"))
        working_slug = working_slug or cast(Optional[str], cmd.channel_metadata.get("working_slug"))
        initiator_session_id = initiator_session_id or cast(
            Optional[str], cmd.channel_metadata.get("initiator_session_id")
        )

    project_path = cmd.project_path
    if not project_path:
        raise ValueError("project_path is required for session creation")
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

    # Derive working_dir and short_project from raw inputs (project_path + subfolder)
    # project_path is the base project, subfolder is the optional worktree/branch path
    if subfolder:
        working_dir = resolve_working_dir(project_path, subfolder)
        working_dir_path = Path(working_dir)
        if not working_dir_path.exists():
            working_dir_path.mkdir(parents=True, exist_ok=True)
        working_dir = str(working_dir_path)
    short_project = get_short_project_name(project_path, subfolder)

    # Build session title using standard format
    # Target agent info not yet known (will be updated when agent starts)
    # Initiator agent info is known if this is an AI-to-AI session
    description = cmd.title or "Untitled"
    base_title = build_session_title(
        computer_name=computer_name,
        short_project=short_project,
        description=description,
        initiator_computer=initiator,
        agent_name=None,
        thinking_mode=None,
        initiator_agent=initiator_agent,
        initiator_mode=initiator_mode,
    )

    # Ensure title is unique (appends counter if needed)
    title = await ensure_unique_title(base_title)

    # Assign random voice for TTS
    voice = get_random_voice()
    if voice:
        await db.assign_voice(session_id, voice)

    # Create session in database first (need session_id for create_channel)
    session = await db.create_session(
        computer_name=computer_name,
        tmux_session_name=tmux_name,
        origin_adapter=str(origin),
        title=title,
        project_path=project_path,
        subdir=subfolder,
        session_id=session_id,
        working_slug=working_slug,
        initiator_session_id=initiator_session_id,
    )

    # Create channel via client (session object passed, adapter_metadata updated in DB)
    await client.create_channel(
        session=session,
        title=title,
        origin_adapter=str(origin),
        target_computer=str(initiator) if initiator else None,
    )

    # Re-fetch session to get updated adapter_metadata (set by create_channel)
    updated_session = await db.get_session(session_id)
    if updated_session is None:
        raise RuntimeError(f"Session {session_id} disappeared after create_channel")
    session = updated_session

    # Create actual tmux session with voice env vars
    voice_env_vars = get_voice_env_vars(voice) if voice else {}

    # Inject TELECLAUDE_SESSION_ID for hook routing
    env_vars = voice_env_vars.copy()
    env_vars["TELECLAUDE_SESSION_ID"] = session_id

    success = await tmux_bridge.ensure_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        session_id=session_id,
        env_vars=env_vars,
    )

    if success:
        logger.info("Created session: %s", session.session_id)
        return {"session_id": session_id, "tmux_session_name": tmux_name}

    # Tmux creation failed - clean up DB and channels
    logger.error(
        "Failed to create tmux session for %s (tmux=%s, working_dir=%s)",
        session.session_id[:8],
        tmux_name,
        working_dir,
    )
    await cleanup_session_resources(session, client)
    await db.close_session(session.session_id)
    logger.error("Failed to create tmux session")
    raise RuntimeError("Failed to create tmux session")


async def list_sessions() -> list[SessionSummary]:
    """List all active sessions from local database.

    Ephemeral request/response for MCP/Redis only - no DB session required.
    UI adapters (Telegram) should not have access to this command.

    Returns:
        List of session summaries.
    """
    sessions = await db.list_sessions()

    summaries: list[SessionSummary] = []
    local_name = config.computer.name
    for s in sessions:
        summaries.append(
            SessionSummary(
                session_id=s.session_id,
                origin_adapter=s.origin_adapter,
                title=s.title,
                project_path=s.project_path,
                subdir=s.subdir,
                thinking_mode=s.thinking_mode or ThinkingMode.SLOW.value,
                active_agent=s.active_agent,
                status="active",
                created_at=s.created_at.isoformat() if s.created_at else None,
                last_activity=s.last_activity.isoformat() if s.last_activity else None,
                last_input=s.last_message_sent,
                last_input_at=s.last_message_sent_at.isoformat() if s.last_message_sent_at else None,
                last_output=s.last_feedback_received,
                last_output_at=s.last_feedback_received_at.isoformat() if s.last_feedback_received_at else None,
                tmux_session_name=s.tmux_session_name,
                initiator_session_id=s.initiator_session_id,
                computer=local_name,
            )
        )

    return summaries


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
        todos: list[TodoInfo] = []
        if project.path:
            todos = await list_todos(project.path)

        project.todos = todos
        projects_with_todos.append(project)

    return projects_with_todos


async def list_todos(project_path: str) -> list[TodoInfo]:
    """List todos from roadmap.md for a project.

    Ephemeral request/response - no DB session required.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of todo objects.
    """
    roadmap_path = Path(project_path) / "todos" / "roadmap.md"

    if not roadmap_path.exists():
        return []

    content = roadmap_path.read_text()
    todos: list[TodoInfo] = []

    # Pattern for todo line: - [ ] slug-name or - [.] slug-name or - [>] slug-name
    pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    # Status marker mapping
    status_map = {
        " ": "pending",
        ".": "ready",
        ">": "in_progress",
    }

    lines = content.split("\n")
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            status_char = match.group(1)
            slug = match.group(2)

            # Extract description (next indented lines)
            description = ""
            for j in range(i + 1, len(lines)):
                next_line = lines[j]
                if next_line.startswith("      "):  # 6 spaces = indented
                    description += next_line.strip() + " "
                elif next_line.strip() == "":
                    continue
                else:
                    break

            # Check for requirements.md and implementation-plan.md
            todos_dir = Path(project_path) / "todos" / slug
            has_requirements = (todos_dir / "requirements.md").exists()
            has_impl_plan = (todos_dir / "implementation-plan.md").exists()

            todos.append(
                TodoInfo(
                    slug=slug,
                    status=status_map.get(status_char, "pending"),
                    description=description.strip() or None,
                    has_requirements=has_requirements,
                    has_impl_plan=has_impl_plan,
                )
            )

    return todos


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

    # Gather system stats
    memory = await asyncio.to_thread(psutil.virtual_memory)
    disk = await asyncio.to_thread(psutil.disk_usage, "/")
    cpu_percent = await asyncio.to_thread(psutil.cpu_percent, 0.1)

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
        tmux_binary=config.computer.tmux_binary,
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
        logger.error("Session %s not found", session_id[:8])
        return {"status": "error", "error": "Session not found"}

    # Get native_log_file from session
    if not session.native_log_file:
        logger.error("No native_log_file for session %s", session_id[:8])
        return {"status": "error", "error": "Session file not found"}

    native_log_file = Path(session.native_log_file)
    if not native_log_file.exists():
        logger.error("Native session file does not exist: %s", native_log_file)
        return {"status": "error", "error": "Session file does not exist"}

    raw_agent_name = session.active_agent
    if not raw_agent_name:
        logger.error("Session %s missing active_agent metadata", session_id[:8])
        return {"status": "error", "error": "Active agent unknown"}

    try:
        agent_name = AgentName.from_str(raw_agent_name)
    except ValueError as exc:
        logger.error("Unknown agent for session %s: %s", session_id[:8], exc)
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
            session_id[:8],
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


async def send_message(
    cmd: SendMessageCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Send a message to a session (tmux input)."""
    session_id = cmd.session_id
    message_text = cmd.text

    logger.debug("Message for session %s: %s...", session_id[:8], message_text[:50])

    session = await db.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=datetime.now(timezone.utc).isoformat(),
    )

    active_agent = session.active_agent
    sanitized_text = tmux_io.wrap_bracketed_paste(message_text)

    working_dir = resolve_working_dir(session.project_path, session.subdir)
    success = await tmux_io.send_text(
        session,
        sanitized_text,
        working_dir=working_dir,
        active_agent=active_agent,
    )

    if not success:
        logger.error("Failed to send command to session %s", session_id[:8])
        await client.send_message(session, "Failed to send command to tmux", metadata=MessageMetadata())
        return

    await db.update_last_activity(session_id)
    await start_polling(session_id, session.tmux_session_name)
    logger.debug("Started polling for session %s", session_id[:8])


async def keys(
    cmd: KeysCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Handle key-based commands via a single KeysCommand."""
    key_name = cmd.key

    if key_name == "cancel":
        await cancel_command(cmd, start_polling, double=False)
        return
    if key_name == "cancel2x":
        await cancel_command(cmd, start_polling, double=True)
        return
    if key_name == "kill":
        await kill_command(cmd, start_polling)
        return
    if key_name == "escape":
        await escape_command(cmd, start_polling, double=False)
        return
    if key_name == "escape2x":
        await escape_command(cmd, start_polling, double=True)
        return
    if key_name == "ctrl":
        await ctrl_command(cmd, client, start_polling)
        return
    if key_name == "tab":
        await tab_command(cmd, start_polling)
        return
    if key_name == "shift_tab":
        await shift_tab_command(cmd, start_polling)
        return
    if key_name == "backspace":
        await backspace_command(cmd, start_polling)
        return
    if key_name == "enter":
        await enter_command(cmd, start_polling)
        return
    if key_name == "key_up":
        await arrow_key_command(cmd, start_polling, "up")
        return
    if key_name == "key_down":
        await arrow_key_command(cmd, start_polling, "down")
        return
    if key_name == "key_left":
        await arrow_key_command(cmd, start_polling, "left")
        return
    if key_name == "key_right":
        await arrow_key_command(cmd, start_polling, "right")
        return

    raise ValueError(f"Unknown keys command: {key_name}")


@with_session
async def cancel_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send CTRL+C (SIGINT) to a session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        double: If True, send CTRL+C twice (for stubborn programs)
    """
    # Send SIGINT (CTRL+C) to the tmux session (TUI interaction, no polling)
    success = await _execute_control_key(
        tmux_io.send_signal,
        session,
        "SIGINT",
    )

    if double and success:
        # Wait a moment then send second SIGINT
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            tmux_io.send_signal,
            session,
            "SIGINT",
        )

    if success:
        logger.info(
            "Sent %s SIGINT to session %s",
            "double" if double else "single",
            session.session_id[:8],
        )
    else:
        logger.error("Failed to send SIGINT to session %s", session.session_id[:8])


@with_session
async def kill_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Force kill foreground process with SIGKILL (guaranteed termination).

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    # Send SIGKILL (forceful termination) to the tmux session (TUI interaction, no polling)
    success = await _execute_control_key(
        tmux_io.send_signal,
        session,
        "SIGKILL",
    )

    if success:
        logger.info("Sent SIGKILL to session %s (force kill)", session.session_id[:8])
    else:
        logger.error("Failed to send SIGKILL to session %s", session.session_id[:8])


@with_session
async def escape_command(
    session: Session,
    cmd: KeysCommand,
    start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send ESCAPE key to a session, optionally followed by text+ENTER.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Optional text to send after ESCAPE (e.g., [":wq"] sends ESCAPE, then :wq+ENTER)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        double: If True, send ESCAPE twice before sending text (if any)
    """

    # If text provided: send ESCAPE (once or twice) + text+ENTER
    if cmd.args:
        text = " ".join(cmd.args)

        # Send ESCAPE first
        success = await tmux_io.send_escape(session)
        if not success:
            logger.error("Failed to send ESCAPE to session %s", session.session_id[:8])
            return

        # Send second ESCAPE if double flag set
        if double:
            await asyncio.sleep(0.1)
            success = await tmux_io.send_escape(session)
            if not success:
                logger.error("Failed to send second ESCAPE to session %s", session.session_id[:8])
                return

        # Wait briefly for ESCAPE to register
        await asyncio.sleep(0.1)

        # Check if process is running for polling decision
        is_process_running = await tmux_io.is_process_running(session)

        # Get active agent for agent-specific escaping
        active_agent = session.active_agent

        # Send text + ENTER
        sanitized_text = tmux_io.wrap_bracketed_paste(text)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        success = await tmux_io.send_text(
            session,
            sanitized_text,
            working_dir=working_dir,
            active_agent=active_agent,
        )

        if not success:
            logger.error("Failed to send text to session %s", session.session_id[:8])
            return

        # Update activity
        await db.update_last_activity(session.session_id)

        # NOTE: Message cleanup handled by UI adapter pre/post handlers

        # Start polling if needed
        if not is_process_running:
            await start_polling(session.session_id, session.tmux_session_name)

        logger.info(
            "Sent %s ESCAPE + '%s' to session %s",
            "double" if double else "single",
            text,
            session.session_id[:8],
        )
        return

    # No args: send ESCAPE only (TUI navigation, no polling)
    success = await _execute_control_key(
        tmux_io.send_escape,
        session,
    )

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            tmux_io.send_escape,
            session,
        )

    if success:
        logger.info(
            "Sent %s ESCAPE to session %s",
            "double" if double else "single",
            session.session_id[:8],
        )
    else:
        logger.error("Failed to send ESCAPE to session %s", session.session_id[:8])


@with_session
async def ctrl_command(
    session: Session,
    cmd: KeysCommand,
    client: "AdapterClient",
    _start_polling: StartPollingFunc,
) -> None:
    """Send CTRL+key combination to a session.

    Args:
        session: Session object (injected by @with_session)
        cmd: KeysCommand payload
        client: AdapterClient for message operations
        start_polling: Function to start polling for a session
    """
    if not cmd.args:
        logger.warning("No key argument provided to ctrl command")
        await client.send_message(
            session,
            "Usage: /ctrl <key> (e.g., /ctrl d for CTRL+D)",
            metadata=MessageMetadata(),
        )
        return

    # Get the key to send (first argument)
    key = cmd.args[0]

    # Send CTRL+key to the tmux session (TUI interaction, no polling)
    success = await _execute_control_key(
        tmux_io.send_ctrl_key,
        session,
        key,
    )

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session.session_id[:8])
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session.session_id[:8])


@with_session
async def tab_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send TAB key to a session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    success = await _execute_control_key(
        tmux_io.send_tab,
        session,
    )

    if success:
        logger.info("Sent TAB to session %s", session.session_id[:8])
    else:
        logger.error("Failed to send TAB to session %s", session.session_id[:8])


@with_session
async def shift_tab_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send SHIFT+TAB key to a session with optional repeat count.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Command arguments (optional repeat count)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    # Parse repeat count from args (default: 1)
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_shift_tab,
        session,
        count,
    )

    if success:
        logger.info("Sent SHIFT+TAB (x%d) to session %s", count, session.session_id[:8])
    else:
        logger.error("Failed to send SHIFT+TAB to session %s", session.session_id[:8])


@with_session
async def backspace_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send BACKSPACE key to a session with optional repeat count.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Command arguments (optional repeat count)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    # Parse repeat count from args (default: 1)
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_backspace,
        session,
        count,
    )

    if success:
        logger.info("Sent BACKSPACE (x%d) to session %s", count, session.session_id[:8])
    else:
        logger.error("Failed to send BACKSPACE to session %s", session.session_id[:8])


@with_session
async def enter_command(
    session: Session,
    _cmd: KeysCommand,
    _start_polling: StartPollingFunc,
) -> None:
    """Send ENTER key to a session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    # Send ENTER key (TUI interaction, no polling)
    success = await _execute_control_key(
        tmux_io.send_enter,
        session,
    )

    if success:
        logger.info("Sent ENTER to session %s", session.session_id[:8])
    else:
        logger.error("Failed to send ENTER to session %s", session.session_id[:8])


@with_session
async def arrow_key_command(
    session: Session,
    cmd: KeysCommand,
    _start_polling: StartPollingFunc,
    direction: str,
) -> None:
    """Send arrow key to a session with optional repeat count.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Command arguments (optional repeat count)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        direction: Arrow direction ('up', 'down', 'left', 'right')
    """

    # Parse repeat count from args (default: 1)
    count = 1
    if cmd.args:
        try:
            count = int(cmd.args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", cmd.args[0])
            count = 1

    success = await _execute_control_key(
        tmux_io.send_arrow_key,
        session,
        direction,
        count,
    )

    if success:
        logger.info(
            "Sent %s arrow key (x%d) to session %s",
            direction.upper(),
            count,
            session.session_id[:8],
        )
    else:
        logger.error(
            "Failed to send %s arrow key to session %s",
            direction.upper(),
            session.session_id[:8],
        )


@with_session
async def close_session(
    session: Session,
    _cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> None:
    """Close session - kill tmux, delete DB record, clean up resources.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with session_id
        client: AdapterClient for channel operations
    """
    await terminate_session(
        session.session_id,
        client,
        reason="close_session",
        session=session,
    )


async def end_session(
    cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> EndSessionHandlerResult:
    """End a session - graceful termination for MCP tool.

    Similar to close_session but designed for MCP tool calls.
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
        return {"status": "error", "message": f"Session {cmd.session_id[:8]} not found"}

    terminated = await terminate_session(
        cmd.session_id,
        client,
        reason="end_session",
        session=session,
        delete_db=False,
    )
    if not terminated:
        return {"status": "error", "message": f"Session {cmd.session_id[:8]} not found"}

    return {
        "status": "success",
        "message": f"Session {cmd.session_id[:8]} ended successfully",
    }


@with_session
async def start_agent(
    session: Session,
    cmd: StartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Start a generic AI agent in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        cmd: StartAgentCommand payload
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute tmux command
    """
    agent_name = cmd.agent_name
    args = list(cmd.args)
    logger.debug(
        "agent_start: session=%s agent_name=%r args=%s config_agents=%s",
        session.session_id[:8],
        agent_name,
        args,
        list(config.agents.keys()),
    )
    agent_config = config.agents.get(agent_name)
    if not agent_config:
        logger.error(
            "Unknown agent requested: %r (session=%s, available=%s)",
            agent_name,
            session.session_id[:8],
            list(config.agents.keys()),
        )
        await client.send_message(session, f"Unknown agent: {agent_name}")
        return

    # Prefer per-session stored thinking_mode if user didn't specify one.
    stored_mode_raw = session.thinking_mode if isinstance(session.thinking_mode, str) else None
    stored_mode = stored_mode_raw or ThinkingMode.SLOW.value

    user_args = list(args)
    thinking_mode = stored_mode
    if user_args and user_args[0] in ThinkingMode._value2member_map_:
        thinking_mode = user_args.pop(0)

    if thinking_mode == ThinkingMode.DEEP.value and agent_name != AgentName.CODEX.value:
        await client.send_message(
            session,
            "deep is only supported for codex. Use fast/med/slow for other agents.",
        )
        return

    start_args = AgentStartArgs(
        agent_name=agent_name,
        thinking_mode=ThinkingMode(thinking_mode),
        user_args=user_args,
    )

    # Persist chosen thinking_mode so subsequent MCP calls (or resumes) can reuse it.
    await db.update_session(session.session_id, thinking_mode=start_args.thinking_mode.value)

    # Include interactive flag when there's a prompt (user_args contains the prompt)
    has_prompt = bool(start_args.user_args)
    base_cmd = get_agent_command(
        start_args.agent_name,
        thinking_mode=start_args.thinking_mode.value,
        interactive=has_prompt,
    )

    cmd_parts = [base_cmd]

    # Add any additional arguments from the user (prompt or flags)
    if start_args.user_args:
        quoted_args = [shlex.quote(arg) for arg in start_args.user_args]
        cmd_parts.extend(quoted_args)

    command_str = " ".join(cmd_parts)
    logger.info("Executing agent start command for %s: %s", agent_name, command_str)

    # Batch all state updates into a single DB write to reduce contention.
    initial_prompt = " ".join(start_args.user_args) if start_args.user_args else None
    truncated_prompt = initial_prompt[:200] if initial_prompt is not None else None

    # Calculate new title (but don't save yet, we want to start the process ASAP)
    new_title = update_title_with_agent(
        session.title,
        agent_name,
        start_args.thinking_mode.value,
        config.computer.name,
    )

    # Perform unified update synchronously to guarantee state
    await db.update_session(
        session.session_id,
        active_agent=agent_name,
        thinking_mode=start_args.thinking_mode.value,
        native_session_id=None,
        native_log_file=None,
        last_message_sent=truncated_prompt,
        last_message_sent_at=datetime.now(timezone.utc).isoformat(),
        title=new_title or session.title,
    )

    # Execute command WITH polling (agents are long-running)
    await execute_terminal_command(session.session_id, command_str, None, True)


@with_session
async def resume_agent(
    session: Session,
    cmd: ResumeAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Resume a generic AI agent session.

    Looks up the native session ID from the database and uses agent-specific
    resume command template to build the correct command.

    Args:
        session: Session object (injected by @with_session)
        cmd: ResumeAgentCommand payload
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute tmux command
    """
    # If no agent_name provided, use active_agent from session
    agent_name = cmd.agent_name or ""
    args = [cmd.native_session_id] if cmd.native_session_id else []

    if not agent_name:
        active = session.active_agent
        if not active:
            await client.send_message(session, "No active agent to resume")
            return
        agent_name = active

    agent_config = config.agents.get(agent_name)
    if not agent_config:
        await client.send_message(session, f"Unknown agent: {agent_name}")
        return

    thinking_raw = session.thinking_mode
    native_session_id_override = args[0].strip() if args else ""
    native_session_id = native_session_id_override or session.native_session_id
    if native_session_id_override:
        await db.update_session(session.session_id, native_session_id=native_session_id_override)

    resume_args = AgentResumeArgs(
        agent_name=agent_name,
        native_session_id=native_session_id,
        thinking_mode=ThinkingMode(thinking_raw),
    )

    command_str = get_agent_command(
        agent=resume_args.agent_name,
        thinking_mode=resume_args.thinking_mode.value,
        exec=False,
        resume=not resume_args.native_session_id,
        native_session_id=resume_args.native_session_id,
    )

    if resume_args.native_session_id:
        logger.info("Resuming %s session %s (from database)", agent_name, resume_args.native_session_id[:8])
    else:
        logger.info("Continuing latest %s session (no native session ID in database)", agent_name)

    # Save active agent
    await db.update_session(session.session_id, active_agent=agent_name)

    # Execute command WITH polling (agents are long-running)
    await execute_terminal_command(session.session_id, command_str, None, True)


@with_session
async def agent_restart(
    session: Session,
    cmd: RestartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Restart an AI agent in the session by resuming the native session.

    Requires native_session_id to be present (fail fast otherwise).
    """
    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = cmd.agent_name or active_agent
    if not target_agent:
        await client.send_message(
            session,
            "❌ Cannot restart agent: no active agent for this session.",
        )
        return

    if not native_session_id:
        await client.send_message(
            session,
            "❌ Cannot restart agent: no native session ID stored. Start the agent first.",
        )
        return

    if not config.agents.get(target_agent):
        await client.send_message(session, f"❌ Unknown agent: {target_agent}")
        return

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id[:8],
        session.tmux_session_name,
    )

    # Kill any existing process (send CTRL+C twice).
    sent = await tmux_io.send_signal(session, "SIGINT")
    if sent:
        await asyncio.sleep(0.2)
        await tmux_io.send_signal(session, "SIGINT")
        await asyncio.sleep(0.5)

    ready = await tmux_io.wait_for_shell_ready(session)
    if not ready:
        await client.send_message(
            session,
            "❌ Agent did not exit after SIGINT. Restart aborted.",
        )
        return

    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=(session.thinking_mode if session.thinking_mode else "slow"),
        exec=False,
        native_session_id=native_session_id,
    )

    await execute_terminal_command(session.session_id, restart_cmd, None, True)


@with_session
async def run_agent_command(
    session: Session,
    cmd: RunAgentCommand,
    _client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Send a slash command directly to the running agent."""
    if not cmd.command:
        logger.warning("run_agent_command called without a command")
        return

    command_text = f"/{cmd.command}".strip()
    if cmd.args:
        command_text = f"{command_text} {cmd.args}".strip()

    await execute_terminal_command(session.session_id, command_text, None, True)
