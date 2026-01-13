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
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypedDict, cast

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import terminal_bridge, terminal_io
from teleclaude.core.agents import AgentName, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.events import EventContext
from teleclaude.core.models import (
    AgentResumeArgs,
    AgentStartArgs,
    CdArgs,
    MessageMetadata,
    Session,
    SessionSummary,
    ThinkingMode,
)
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX, cleanup_session_resources, terminate_session
from teleclaude.core.session_utils import build_session_title, ensure_unique_title, update_title_with_agent
from teleclaude.core.terminal_events import TerminalEventMetadata
from teleclaude.core.voice_assignment import get_random_voice, get_voice_env_vars
from teleclaude.types import CpuStats, DiskStats, MemoryStats, SystemStats
from teleclaude.utils.transcript import get_transcript_parser_info, parse_session_transcript

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


# TypedDict definitions for command handler return types
class SessionListItem(TypedDict, total=False):
    """Session list item returned by handle_list_sessions."""

    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    status: str
    created_at: str
    last_activity: str
    computer: str  # Added by MCP server for consistency


class ProjectInfo(TypedDict):
    """Project info returned by handle_list_projects."""

    name: str
    desc: str
    path: str


class TodoInfo(TypedDict):
    """Todo item returned by handle_list_todos."""

    slug: str
    status: str
    description: str | None
    has_requirements: bool
    has_impl_plan: bool


class ProjectWithTodosInfo(TypedDict):
    """Project info with embedded todos."""

    name: str
    desc: str | None
    path: str
    todos: list[TodoInfo]


class ComputerInfoData(TypedDict):
    """Computer info returned by handle_get_computer_info."""

    user: str | None
    host: str | None
    role: str | None
    system_stats: SystemStats | None
    tmux_binary: str | None


class SessionDataPayload(TypedDict, total=False):
    """Session data payload returned by handle_get_session_data."""

    status: str  # Required - always present
    session_id: str
    transcript: str | None
    last_activity: str | None
    working_directory: str | None
    error: str  # Present in error responses
    project_dir: str  # Sometimes present
    messages: str  # Sometimes present
    created_at: str | None  # Sometimes present


class EndSessionHandlerResult(TypedDict):
    """Result from handle_end_session."""

    status: str
    message: str


# Type alias for start_polling function
StartPollingFunc = Callable[[str, str], Awaitable[None]]


# Decorator to inject session from context (removes boilerplate)
def with_session(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator that extracts and injects session from context.

    Removes boilerplate from command handlers:
    - Extracts session_id from context (crashes if missing - contract violation)
    - Fetches session from db (crashes if None - contract violation)
    - Injects session as first parameter to handler

    Handler signature changes from:
        async def handler(context, ...) -> None
    To:
        async def handler(session, context, ...) -> None

    Example:
        @with_session
        async def handle_cancel(session: Session, context: EventContext, ...) -> None:
            # session is already validated and injected
            await terminal_io.send_signal(session, "SIGINT")
    """

    @functools.wraps(func)
    async def wrapper(context: EventContext, *args: object, **kwargs: object) -> None:
        # Extract session_id (let it crash if missing - our code emitted this event)
        # SystemCommandContext doesn't have session_id, but @with_session is only used for session-based commands
        assert hasattr(context, "session_id"), f"Context {type(context).__name__} missing session_id"
        session_id: str = str(
            context.session_id  # pyright: ignore[reportAttributeAccessIssue]
        )

        # Get session (let it crash if None - session should exist)
        session = await db.get_session(session_id)
        if session is None:
            raise RuntimeError(f"Session {session_id} not found - this should not happen")

        # Call handler with session injected as first parameter
        await func(session, context, *args, **kwargs)

    return wrapper


async def _execute_control_key(
    terminal_action: Callable[..., Awaitable[bool]],
    session: Session,
    *terminal_args: object,
) -> bool:
    """Execute control/navigation key without polling (TUI interaction).

    Used for keys that interact with TUIs and don't produce shell output:
    arrow keys, tab, shift+tab, escape, ctrl, cancel, kill.

    Args:
        terminal_action: Terminal bridge function to execute
        session: Session object (contains tmux_session_name)
        *terminal_args: Additional arguments for terminal_action

    Returns:
        True if terminal action succeeded, False otherwise
    """
    return await terminal_action(session, *terminal_args)


async def handle_create_session(  # pylint: disable=too-many-locals  # Session creation requires many variables
    _context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: "AdapterClient",
) -> dict[str, str]:
    """Create a new terminal session.

    Args:
        context: Command context
        args: Command arguments (optional custom title)
        metadata: Message metadata (adapter_type, project_dir, etc.)
        client: AdapterClient for channel operations

    Returns:
        Minimal session payload with session_id
    """
    # Get adapter_type from metadata
    adapter_type = metadata.adapter_type
    if not adapter_type:
        raise ValueError("Metadata missing adapter_type")

    computer_name = config.computer.name
    working_dir = os.path.expanduser(os.path.expandvars(config.computer.default_working_dir))

    terminal_meta = TerminalEventMetadata.from_channel_metadata(metadata.channel_metadata)

    # For AI-to-AI sessions, use project_dir from metadata
    project_dir = metadata.project_dir
    if project_dir:
        working_dir = os.path.expanduser(os.path.expandvars(project_dir))

    # tmux silently falls back to its own cwd if -c points at a non-existent directory.
    # This shows up as sessions "starting in /tmp" (or similar) even though we asked for a project dir.
    working_dir_path = Path(working_dir)
    if not working_dir_path.is_absolute():
        raise ValueError(f"Working directory must be an absolute path: {working_dir}")
    if not working_dir_path.exists():
        try:
            working_dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ValueError(f"Working directory does not exist and could not be created: {working_dir}") from e
    if not working_dir_path.is_dir():
        raise ValueError(f"Working directory is not a directory: {working_dir}")
    working_dir = str(working_dir_path)

    # Generate tmux session name with prefix for TeleClaude ownership
    session_id = str(uuid.uuid4())
    tmux_name = f"{TMUX_SESSION_PREFIX}{session_id[:8]}"

    # Extract metadata from channel_metadata if present (AI-to-AI session)
    initiator = None
    initiator_agent = None
    initiator_mode = None
    subfolder = None
    working_slug = None
    initiator_session_id = None
    if metadata.channel_metadata:
        initiator_raw = metadata.channel_metadata.get("target_computer")
        initiator = str(initiator_raw) if initiator_raw else None
        initiator_agent_raw = metadata.channel_metadata.get("initiator_agent")
        initiator_agent = str(initiator_agent_raw) if initiator_agent_raw else None
        initiator_mode_raw = metadata.channel_metadata.get("initiator_mode")
        initiator_mode = str(initiator_mode_raw) if initiator_mode_raw else None
        subfolder_raw = metadata.channel_metadata.get("subfolder")
        subfolder = str(subfolder_raw) if subfolder_raw else None
        working_slug_raw = metadata.channel_metadata.get("working_slug")
        working_slug = str(working_slug_raw) if working_slug_raw else None
        initiator_session_id_raw = metadata.channel_metadata.get("initiator_session_id")
        initiator_session_id = str(initiator_session_id_raw) if initiator_session_id_raw else None

    # Derive working_dir and short_project from raw inputs (project_dir + subfolder)
    # project_dir is the base project, subfolder is the optional worktree/branch path
    if subfolder:
        # Append subfolder to get actual working directory
        working_dir = f"{working_dir}/{subfolder}"
        working_dir_path = Path(working_dir)
        if not working_dir_path.exists():
            working_dir_path.mkdir(parents=True, exist_ok=True)
        working_dir = str(working_dir_path)
        # Derive short_project from raw inputs: project_name/slug
        project_name = project_dir.rstrip("/").split("/")[-1] if project_dir else "unknown"
        slug = subfolder.split("/")[-1]
        short_project = f"{project_name}/{slug}"
    else:
        # No subfolder - just use last folder name
        short_project = working_dir.rstrip("/").split("/")[-1] if working_dir else "unknown"

    # Build session title using standard format
    # Target agent info not yet known (will be updated when agent starts)
    # Initiator agent info is known if this is an AI-to-AI session
    description = " ".join(args) if args else "Untitled"
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
    # Voice is stored keyed by session_id now, then copied to claude_session_id key on session_start event
    voice = get_random_voice()
    if voice:
        await db.assign_voice(session_id, voice)

    # Create session in database first (need session_id for create_channel)
    # session_id was generated earlier for tmux naming
    session = await db.create_session(
        computer_name=computer_name,
        tmux_session_name=tmux_name,
        origin_adapter=str(adapter_type),
        title=title,
        working_directory=working_dir,
        session_id=session_id,
        working_slug=working_slug,
        initiator_session_id=initiator_session_id,
    )

    if adapter_type == "terminal" and (terminal_meta.tty_path or terminal_meta.parent_pid is not None):
        await db.update_session(
            session_id,
            native_tty_path=terminal_meta.tty_path,
            native_pid=terminal_meta.parent_pid,
        )

    # Create channel via client (session object passed, adapter_metadata updated in DB)
    # Pass initiator (target_computer) for AI-to-AI sessions so stop events can be forwarded
    await client.create_channel(
        session=session,
        title=title,
        origin_adapter=str(adapter_type),
        target_computer=str(initiator) if initiator else None,
    )

    # Re-fetch session to get updated adapter_metadata (set by create_channel)
    updated_session = await db.get_session(session_id)
    if updated_session is None:
        raise RuntimeError(f"Session {session_id} disappeared after create_channel")
    session = updated_session

    # Create actual tmux session with voice env vars
    voice_env_vars = get_voice_env_vars(voice) if voice else {}

    # Inject TELECLAUDE_SESSION_ID for hook routing; mcp-wrapper uses TMPDIR marker.
    env_vars = voice_env_vars.copy()
    env_vars["TELECLAUDE_SESSION_ID"] = session_id

    success = await terminal_bridge.create_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        session_id=session_id,
        env_vars=env_vars,
    )

    if success:
        # Send welcome feedback (temporary, auto-deleted on first user input)
        welcome = f"""Session created!

Computer: {computer_name}
Working directory: {working_dir}

You can now send commands to this session.
"""
        await client.send_message(session, welcome, ephemeral=False)
        logger.info("Created session: %s", session.session_id)
        return {"session_id": session_id, "tmux_session_name": tmux_name}

    # Tmux creation failed - clean up DB and channels
    await cleanup_session_resources(session, client)
    await db.delete_session(session.session_id)
    logger.error("Failed to create tmux session")
    raise RuntimeError("Failed to create tmux session")


async def handle_list_sessions() -> list[SessionListItem]:
    """List all active sessions from local database.

    Ephemeral request/response for MCP/Redis only - no DB session required.
    UI adapters (Telegram) should not have access to this command.

    Returns:
        List of session dicts with fields: session_id, origin_adapter, title,
        working_directory, status, created_at, last_activity
    """
    sessions = await db.list_sessions()

    summaries: list[SessionSummary] = []
    for s in sessions:
        summaries.append(
            SessionSummary(
                session_id=s.session_id,
                origin_adapter=s.origin_adapter,
                title=s.title,
                working_directory=s.working_directory,
                thinking_mode=s.thinking_mode or ThinkingMode.SLOW.value,
                active_agent=s.active_agent,
                status="active",
                created_at=s.created_at.isoformat() if s.created_at else None,
                last_activity=s.last_activity.isoformat() if s.last_activity else None,
                last_input=s.last_message_sent,
                last_output=s.last_feedback_received,
                tmux_session_name=s.tmux_session_name,
                initiator_session_id=s.initiator_session_id,
            )
        )

    return cast(list[SessionListItem], [s.to_dict() for s in summaries])


async def handle_list_projects() -> list[dict[str, str]]:
    """List trusted project directories.

    Ephemeral request/response - no DB session required.

    Returns:
        List of directory dicts with name, desc, path
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
                {
                    "name": trusted_dir.name,
                    "desc": trusted_dir.desc,
                    "path": expanded_path,
                }
            )

    return dirs_data


async def handle_list_projects_with_todos() -> list[ProjectWithTodosInfo]:
    """List projects with their todos included (local only)."""
    raw_projects = await handle_list_projects()
    projects_with_todos: list[ProjectWithTodosInfo] = []

    for project in raw_projects:
        path = project.get("path", "")
        todos: list[TodoInfo] = []
        if path:
            todos = await handle_list_todos(str(path))

        projects_with_todos.append(
            {
                "name": project.get("name", ""),
                "desc": project.get("desc"),
                "path": path,
                "todos": todos,
            }
        )

    return projects_with_todos


async def handle_list_todos(project_path: str) -> list[TodoInfo]:
    """List todos from roadmap.md for a project.

    Ephemeral request/response - no DB session required.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of todo dicts with slug, status, description, has_requirements, has_impl_plan
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


async def handle_get_computer_info() -> ComputerInfoData:
    """Return computer info including system stats.

    Ephemeral request/response - no DB session required.

    Returns:
        Dict with user, role, host, and system_stats (memory, disk, cpu)
    """
    logger.debug("handle_get_computer_info() called")

    # Build info from config - design by contract: these fields are required
    if not config.computer.user or not config.computer.role or not config.computer.host:
        raise ValueError("Computer configuration is incomplete - user, role, and host are required")

    # Gather system stats
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # Build typed system stats
    memory_total = memory.total
    memory_available = memory.available
    memory_percent = memory.percent
    disk_total = disk.total
    disk_free = disk.free
    disk_percent = disk.percent
    cpu_percent_value = cpu_percent

    memory_stats: MemoryStats = {
        "total_gb": round(memory_total / (1024**3), 1),
        "available_gb": round(memory_available / (1024**3), 1),
        "percent_used": memory_percent,
    }
    disk_stats: DiskStats = {
        "total_gb": round(disk_total / (1024**3), 1),
        "free_gb": round(disk_free / (1024**3), 1),
        "percent_used": disk_percent,
    }
    cpu_stats: CpuStats = {
        "percent_used": cpu_percent_value,
    }
    system_stats: SystemStats = {
        "memory": memory_stats,
        "disk": disk_stats,
        "cpu": cpu_stats,
    }

    info_data: ComputerInfoData = {
        "user": config.computer.user,
        "role": config.computer.role,
        "host": config.computer.host,
        "system_stats": system_stats,
        "tmux_binary": config.computer.tmux_binary,
    }

    logger.debug("handle_get_computer_info() returning info: %s", info_data)
    return info_data


async def handle_get_session_data(
    context: EventContext,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 2000,
) -> SessionDataPayload:
    """Get session data from native_log_file.

    Reads the Agent session file (JSONL format) and parses to markdown.
    Uses same parsing as download functionality for consistent formatting.
    Supports timestamp filtering and character limit.

    Args:
        context: Command context with session_id
        since_timestamp: Optional ISO 8601 UTC start filter
        until_timestamp: Optional ISO 8601 UTC end filter
        tail_chars: Max chars to return (default 2000, 0 for unlimited)

    Returns:
        Dict with session data and markdown-formatted messages
    """

    # Get session_id from context
    if not hasattr(context, "session_id"):
        logger.error("No session_id in context for get_session_data")
        return {"status": "error", "error": "No session_id provided"}

    session_id = str(context.session_id)  # pyright: ignore[reportAttributeAccessIssue]

    # Get session from database
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
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            tail_chars=tail_chars,
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
        "project_dir": session.working_directory,
        "messages": markdown_content,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
    }


@with_session
async def handle_cancel_command(
    session: Session,
    _context: EventContext,
    _client: "AdapterClient",
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
        terminal_io.send_signal,
        session,
        "SIGINT",
    )

    if double and success:
        # Wait a moment then send second SIGINT
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            terminal_io.send_signal,
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
async def handle_kill_command(
    session: Session,
    _context: EventContext,
    _client: "AdapterClient",
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
        terminal_io.send_signal,
        session,
        "SIGKILL",
    )

    if success:
        logger.info("Sent SIGKILL to session %s (force kill)", session.session_id[:8])
    else:
        logger.error("Failed to send SIGKILL to session %s", session.session_id[:8])


@with_session
async def handle_escape_command(
    session: Session,
    _context: EventContext,
    args: list[str],
    _client: "AdapterClient",
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
    if args:
        text = " ".join(args)

        # Send ESCAPE first
        success = await terminal_io.send_escape(session)
        if not success:
            logger.error("Failed to send ESCAPE to session %s", session.session_id[:8])
            return

        # Send second ESCAPE if double flag set
        if double:
            await asyncio.sleep(0.1)
            success = await terminal_io.send_escape(session)
            if not success:
                logger.error("Failed to send second ESCAPE to session %s", session.session_id[:8])
                return

        # Wait briefly for ESCAPE to register
        await asyncio.sleep(0.1)

        # Check if process is running for polling decision
        is_process_running = await terminal_io.is_process_running(session)

        # Get active agent for agent-specific escaping
        active_agent = session.active_agent

        # Send text + ENTER
        sanitized_text = terminal_io.wrap_bracketed_paste(text)
        success = await terminal_io.send_text(
            session,
            sanitized_text,
            working_dir=session.working_directory,
            active_agent=active_agent,
        )

        if not success:
            logger.error("Failed to send text to session %s", session.session_id[:8])
            return

        # Update activity
        await db.update_last_activity(session.session_id)

        # NOTE: Message cleanup now handled by AdapterClient.handle_event()

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
        terminal_io.send_escape,
        session,
    )

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            terminal_io.send_escape,
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
async def handle_ctrl_command(
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    _start_polling: StartPollingFunc,
) -> None:
    """Send CTRL+key combination to a session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Command arguments (key to send with CTRL)
        client: AdapterClient for message operations
        start_polling: Function to start polling for a session
    """
    if not args:
        logger.warning("No key argument provided to ctrl command")
        await client.send_message(
            session,
            "Usage: /ctrl <key> (e.g., /ctrl d for CTRL+D)",
            metadata=MessageMetadata(),
        )

        # Track both command message AND feedback message for deletion
        # Track command message (e.g., /ctrl)
        message_id = cast(Optional[str], getattr(context, "message_id", None))
        if message_id:
            await db.add_pending_deletion(session.session_id, str(message_id))
            logger.debug(
                "Tracked command message %s for deletion (session %s)",
                message_id,
                session.session_id[:8],
            )

        # Note: Feedback message auto-tracked by send_message(ephemeral=True)

        return

    # Get the key to send (first argument)
    key = args[0]

    # Send CTRL+key to the tmux session (TUI interaction, no polling)
    success = await _execute_control_key(
        terminal_io.send_ctrl_key,
        session,
        key,
    )

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session.session_id[:8])
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session.session_id[:8])


@with_session
async def handle_tab_command(
    session: Session,
    _context: EventContext,
    _client: "AdapterClient",
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
        terminal_io.send_tab,
        session,
    )

    if success:
        logger.info("Sent TAB to session %s", session.session_id[:8])
    else:
        logger.error("Failed to send TAB to session %s", session.session_id[:8])


@with_session
async def handle_shift_tab_command(
    session: Session,
    _context: EventContext,
    args: list[str],
    _client: "AdapterClient",
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
    if args:
        try:
            count = int(args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", args[0])
            count = 1

    success = await _execute_control_key(
        terminal_io.send_shift_tab,
        session,
        count,
    )

    if success:
        logger.info("Sent SHIFT+TAB (x%d) to session %s", count, session.session_id[:8])
    else:
        logger.error("Failed to send SHIFT+TAB to session %s", session.session_id[:8])


@with_session
async def handle_backspace_command(
    session: Session,
    _context: EventContext,
    args: list[str],
    _client: "AdapterClient",
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
    if args:
        try:
            count = int(args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", args[0])
            count = 1

    success = await _execute_control_key(
        terminal_io.send_backspace,
        session,
        count,
    )

    if success:
        logger.info("Sent BACKSPACE (x%d) to session %s", count, session.session_id[:8])
    else:
        logger.error("Failed to send BACKSPACE to session %s", session.session_id[:8])


@with_session
async def handle_enter_command(
    session: Session,
    _context: EventContext,
    _client: "AdapterClient",
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
        terminal_io.send_enter,
        session,
    )

    if success:
        logger.info("Sent ENTER to session %s", session.session_id[:8])
    else:
        logger.error("Failed to send ENTER to session %s", session.session_id[:8])


@with_session
async def handle_arrow_key_command(
    session: Session,
    _context: EventContext,
    args: list[str],
    _client: "AdapterClient",
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
    if args:
        try:
            count = int(args[0])
            if count < 1:
                logger.warning("Invalid repeat count %d (must be >= 1), using 1", count)
                count = 1
        except ValueError:
            logger.warning("Invalid repeat count '%s', using 1", args[0])
            count = 1

    success = await _execute_control_key(
        terminal_io.send_arrow_key,
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
async def handle_rename_session(
    session: Session,
    _context: EventContext,
    args: list[str],
    client: "AdapterClient",
) -> None:
    """Rename session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context
        args: Command arguments (new name)
        client: AdapterClient for message operations
    """
    if not args:
        logger.warning("No name argument provided to rename command")
        return

    # Build new title with computer name prefix
    computer_name = config.computer.name
    new_title = f"[{computer_name}] {' '.join(args)}"

    # Update in database
    await db.update_session(session.session_id, title=new_title)

    # Update channel title via AdapterClient (looks up session internally)
    success = await client.update_channel_title(session, new_title)
    if success:
        logger.info("Renamed session %s to '%s'", session.session_id[:8], new_title)

        # Cleanup old messages AND delete current command
        # NOTE: Message cleanup now handled by AdapterClient.handle_event()

        # Send feedback message (plain text, no Markdown)
        await client.send_message(session, f"Session renamed to: {new_title}", metadata=MessageMetadata())
        # Note: Feedback message auto-tracked by send_message(ephemeral=True)
    else:
        logger.error("Failed to update channel title for session %s", session.session_id[:8])
        await client.send_message(session, "Failed to update channel title", metadata=MessageMetadata())
        # Note: Error message auto-tracked by send_message(ephemeral=True)


@with_session
async def handle_cd_session(
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Change directory in session or list trusted directories.

    Args:
        context: Command context with session_id and message_id
        args: Command arguments (directory path or empty to list)
        client: AdapterClient for message operations
        execute_terminal_command: Function to execute terminal command
    """

    # Normalize args to a single path or None
    normalized = " ".join([arg.strip() for arg in args if arg.strip()])
    cd_args = CdArgs(path=normalized or None)

    # If no args, list trusted directories
    if not cd_args.path:
        # Get all trusted dirs (includes TC WORKDIR from get_all_trusted_dirs)
        all_trusted_dirs = config.computer.get_all_trusted_dirs()

        lines = ["**Trusted Directories:**\n"]
        for idx, trusted_dir in enumerate(all_trusted_dirs, 1):
            # Show name - desc (if desc available)
            display_text = f"{trusted_dir.name} - {trusted_dir.desc}" if trusted_dir.desc else trusted_dir.name
            lines.append(f"{idx}. {display_text}")

        response = "\n".join(lines)
        await client.send_message(session, response)
        # Note: Help message auto-tracked by send_message(ephemeral=True)
        return

    # Change to specified directory
    target_dir = cd_args.path

    # Handle TC WORKDIR special case
    if target_dir == "TC WORKDIR":
        target_dir = os.path.expanduser(config.computer.default_working_dir)
    cd_command = f"cd {shlex.quote(target_dir)}"

    # Execute command WITHOUT polling (cd is instant)
    message_id = str(getattr(context, "message_id", ""))
    success = await execute_terminal_command(session.session_id, cd_command, message_id, False)

    # Save working directory to DB if successful
    if success:
        await db.update_session(session.session_id, working_directory=target_dir)
        logger.debug(
            "Updated working_directory for session %s: %s",
            session.session_id[:8],
            target_dir,
        )


@with_session
async def handle_exit_session(
    session: Session,
    _context: EventContext,
    client: "AdapterClient",
) -> None:
    """Exit session - kill tmux, delete DB record, clean up resources.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with session_id
        client: AdapterClient for channel operations
    """
    await terminate_session(
        session.session_id,
        client,
        reason="exit",
        session=session,
    )


async def handle_end_session(
    session_id: str,
    client: "AdapterClient",
) -> EndSessionHandlerResult:
    """End a session - graceful termination for MCP tool.

    Similar to handle_exit_session but designed for MCP tool calls.
    Kills tmux, deletes the session, cleans up resources.

    Args:
        session_id: Session identifier
        client: AdapterClient for channel operations

    Returns:
        dict with status and message
    """
    # Get session from DB
    session = await db.get_session(session_id)
    if not session:
        return {"status": "error", "message": f"Session {session_id[:8]} not found"}

    terminated = await terminate_session(
        session_id,
        client,
        reason="end_session",
        session=session,
    )
    if not terminated:
        return {"status": "error", "message": f"Session {session_id[:8]} not found"}

    return {
        "status": "success",
        "message": f"Session {session_id[:8]} ended successfully",
    }


@with_session
async def handle_agent_start(
    session: Session,
    context: EventContext,
    agent_name: str,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Start a generic AI agent in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        agent_name: The name of the agent to start (e.g., "claude", "gemini")
        args: Command arguments (passed to agent command)
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    logger.debug(
        "handle_agent_start: session=%s agent_name=%r args=%s config_agents=%s",
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

    cmd = " ".join(cmd_parts)
    logger.info("Executing agent start command for %s: %s", agent_name, cmd)

    # Save active agent and clear previous native session bindings.
    # Also save initial prompt as last_message_sent for TUI display (nested sessions)
    initial_prompt = " ".join(start_args.user_args) if start_args.user_args else None
    await db.update_session(
        session.session_id,
        active_agent=agent_name,
        thinking_mode=start_args.thinking_mode.value,
        native_session_id=None,
        native_log_file=None,
        last_message_sent=initial_prompt[:200] if initial_prompt else None,
    )

    # Update session title to include agent info (replaces $Computer with Agent-mode@Computer)
    new_title = update_title_with_agent(
        session.title,
        agent_name,
        start_args.thinking_mode.value,
        config.computer.name,
    )
    if new_title:
        await db.update_session(session.session_id, title=new_title)
        logger.info("Updated session title with agent info: %s", new_title)

    # Execute command WITH polling (agents are long-running)
    message_id = str(getattr(context, "message_id", ""))
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session
async def handle_agent_resume(
    session: Session,
    context: EventContext,
    agent_name: str,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Resume a generic AI agent session.

    Looks up the native session ID from the database and uses agent-specific
    resume command template to build the correct command.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        agent_name: The name of the agent to resume (if empty, uses active_agent from UX state)
        args: Command arguments (currently unused - session ID comes from database)
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    # If no agent_name provided, use active_agent from session
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

    thinking_raw = session.thinking_mode if isinstance(session.thinking_mode, str) else None
    resume_args = AgentResumeArgs(
        agent_name=agent_name,
        native_session_id=session.native_session_id,
        thinking_mode=ThinkingMode(thinking_raw) if thinking_raw else ThinkingMode.SLOW,
    )

    cmd = get_agent_command(
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
    message_id = str(getattr(context, "message_id", ""))
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session
async def handle_agent_restart(
    session: Session,
    context: EventContext,
    agent_name: str,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Restart an AI agent in the session by resuming the native session.

    Requires native_session_id to be present (fail fast otherwise).
    """
    _ = args  # unused (kept for parity with other agent handlers)
    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = agent_name or active_agent
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
    sent = await terminal_io.send_signal(session, "SIGINT")
    if sent:
        await asyncio.sleep(0.2)
        await terminal_io.send_signal(session, "SIGINT")
        await asyncio.sleep(0.5)

    ready = await terminal_io.wait_for_shell_ready(session)
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

    message_id = str(getattr(context, "message_id", ""))
    await execute_terminal_command(session.session_id, restart_cmd, message_id, True)


@with_session
async def handle_claude_session(
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Start Claude agent in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to claude command)
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_start(session, context, "claude", args, client, execute_terminal_command)


@with_session
async def handle_claude_resume_session(
    session: Session,
    context: EventContext,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Resume Agent session using explicit session ID from metadata.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_resume(session, context, "claude", [], client, execute_terminal_command)


@with_session
async def handle_gemini_session(
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Start Gemini in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to gemini command)
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_start(session, context, "gemini", args, client, execute_terminal_command)


@with_session
async def handle_gemini_resume_session(
    session: Session,
    context: EventContext,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Resume Gemini session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_resume(session, context, "gemini", [], client, execute_terminal_command)


@with_session
async def handle_codex_session(
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Start Codex in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to codex command)
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_start(session, context, "codex", args, client, execute_terminal_command)


@with_session
async def handle_codex_resume_session(
    session: Session,
    context: EventContext,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, Optional[str], bool], Awaitable[bool]],
) -> None:
    """Resume Codex session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        client: AdapterClient for sending feedback
        execute_terminal_command: Function to execute terminal command
    """
    await handle_agent_resume(session, context, "codex", [], client, execute_terminal_command)
