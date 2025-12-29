"""Command handlers for TeleClaude bot commands.

Extracted from daemon.py to reduce file size and improve organization.
All handlers are stateless functions with explicit dependencies.
"""

import asyncio
import functools
import os
import shlex
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypedDict, cast

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import terminal_bridge
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
from teleclaude.core.session_cleanup import (
    TMUX_SESSION_PREFIX,
    cleanup_session_resources,
)
from teleclaude.core.session_utils import ensure_unique_title
from teleclaude.core.voice_assignment import get_random_voice, get_voice_env_vars
from teleclaude.utils.transcript import (
    get_transcript_parser_info,
    parse_session_transcript,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


# TypedDicts for structured data


class MemoryStats(TypedDict):
    """Memory statistics structure."""

    total_gb: float
    available_gb: float
    percent_used: float


class DiskStats(TypedDict):
    """Disk statistics structure."""

    total_gb: float
    free_gb: float
    percent_used: float


class CpuStats(TypedDict):
    """CPU statistics structure."""

    percent_used: float


class SystemStats(TypedDict):
    """System statistics structure."""

    memory: MemoryStats
    disk: DiskStats
    cpu: CpuStats


# Type alias for start_polling function
StartPollingFunc = Callable[[str, str], Awaitable[None]]


def get_short_project_name(project_path: str) -> str:
    """Extract short project name from path (last 2 parts).

    Args:
        project_path: Full path like /home/morriz/apps/TeleClaude

    Returns:
        Short name like apps/TeleClaude
    """
    parts = project_path.rstrip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else "unknown"


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
            await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
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
    return await terminal_action(session.tmux_session_name, *terminal_args)


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
    logger.info(
        "handle_create_session: adapter_type=%s, channel_metadata=%s",
        metadata.adapter_type,
        metadata.channel_metadata,
    )
    # Get adapter_type from metadata
    adapter_type = metadata.adapter_type
    if not adapter_type:
        raise ValueError("Metadata missing adapter_type")

    computer_name = config.computer.name
    working_dir = os.path.expanduser(os.path.expandvars(config.computer.default_working_dir))
    terminal_size = "120x40"  # Default terminal size

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

    # Get short project name for title
    short_project = get_short_project_name(working_dir)

    # Extract initiator from channel_metadata if present
    initiator = None
    if metadata.channel_metadata:
        initiator = metadata.channel_metadata.get("target_computer")

    # Create topic first with custom title if provided
    # For AI-to-AI sessions (initiator present), use "initiator > computer[project]" format
    # For human sessions, use "computer[project]" format
    if initiator:
        # AI-to-AI: "AI:$MozBook > $RasPi[apps/TeleClaude] - New session"
        if args and len(args) > 0:
            base_title = f"AI:${initiator} > ${computer_name}[{short_project}] - {' '.join(args)}"
        else:
            base_title = f"AI:${initiator} > ${computer_name}[{short_project}] - New session"
    else:
        # Human-initiated (Telegram): "$RasPi[apps/TeleClaude] - New session"
        if args and len(args) > 0:
            base_title = f"${computer_name}[{short_project}] - {' '.join(args)}"
        else:
            base_title = f"${computer_name}[{short_project}] - New session"

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
        terminal_size=terminal_size,
        working_directory=working_dir,
        session_id=session_id,
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
    cols, rows = map(int, terminal_size.split("x"))
    voice_env_vars = get_voice_env_vars(voice) if voice else {}

    # Inject TELECLAUDE_SESSION_ID so mcp-wrapper knows who it is
    env_vars = voice_env_vars.copy()
    env_vars["TELECLAUDE_SESSION_ID"] = session_id

    success = await terminal_bridge.create_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        cols=cols,
        rows=rows,
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
        await client.send_feedback(session, welcome, MessageMetadata(), persistent=True)
        logger.info("Created session: %s", session.session_id)
        return {"session_id": session_id}

    # Tmux creation failed - clean up DB and channels
    await cleanup_session_resources(session, client)
    await db.delete_session(session.session_id)
    logger.error("Failed to create tmux session")
    raise RuntimeError("Failed to create tmux session")


async def handle_list_sessions() -> list[dict[str, object]]:
    """List all active sessions from local database.

    Ephemeral request/response for MCP/Redis only - no DB session required.
    UI adapters (Telegram) should not have access to this command.

    Returns:
        List of session dicts with fields: session_id, origin_adapter, title,
        working_directory, status, created_at, last_activity
    """
    sessions = await db.list_sessions(closed=False)

    summaries: list[SessionSummary] = []
    for s in sessions:
        ux_state = await db.get_ux_state(s.session_id)
        summaries.append(
            SessionSummary(
                session_id=s.session_id,
                origin_adapter=s.origin_adapter,
                title=s.title,
                working_directory=s.working_directory,
                thinking_mode=ux_state.thinking_mode or ThinkingMode.SLOW.value,
                status="closed" if s.closed else "active",
                created_at=s.created_at.isoformat() if s.created_at else None,
                last_activity=s.last_activity.isoformat() if s.last_activity else None,
            )
        )

    return [s.to_dict() for s in summaries]


async def handle_list_projects() -> list[dict[str, str]]:
    """List trusted project directories.

    Ephemeral request/response - no DB session required.

    Returns:
        List of directory dicts with name, desc, location
    """
    # Get all trusted dirs (includes default_working_dir merged in)
    all_trusted_dirs = config.computer.get_all_trusted_dirs()

    # Build structured response with name, desc, location
    # Filter to only existing directories
    dirs_data = []
    for trusted_dir in all_trusted_dirs:
        expanded_location = os.path.expanduser(os.path.expandvars(trusted_dir.path))
        if Path(expanded_location).exists():
            dirs_data.append(
                {
                    "name": trusted_dir.name,
                    "desc": trusted_dir.desc,
                    "location": expanded_location,
                }
            )

    return dirs_data


async def handle_get_computer_info() -> dict[str, object]:
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

    info_data: dict[str, object] = {
        "user": config.computer.user,
        "role": config.computer.role,
        "host": config.computer.host,
        "system_stats": system_stats,
    }

    logger.debug("handle_get_computer_info() returning info: %s", info_data)
    return info_data


async def handle_get_session_data(
    context: EventContext,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
) -> dict[str, object]:
    """Get session data from native_log_file.

    Reads the Agent session file (JSONL format) and parses to markdown.
    Uses same parsing as download functionality for consistent formatting.
    Supports timestamp filtering and character limit.

    Args:
        context: Command context with session_id
        since_timestamp: Optional ISO 8601 UTC start filter
        until_timestamp: Optional ISO 8601 UTC end filter
        tail_chars: Max chars to return (default 5000, 0 for unlimited)

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

    if session.closed:
        logger.info("Session %s is closed", session_id[:8])
        return {"status": "closed", "session_id": session_id, "error": "Session is closed"}

    # Get ux_state to get native_log_file
    ux_state = await db.get_ux_state(session_id)
    if not ux_state or not ux_state.native_log_file:
        logger.error("No native_log_file for session %s", session_id[:8])
        return {"status": "error", "error": "Session file not found"}

    native_log_file = Path(ux_state.native_log_file)
    if not native_log_file.exists():
        logger.error("Native session file does not exist: %s", native_log_file)
        return {"status": "error", "error": "Session file does not exist"}

    raw_agent_name = ux_state.active_agent
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
        terminal_bridge.send_signal,
        session,
        "SIGINT",
    )

    if double and success:
        # Wait a moment then send second SIGINT
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            terminal_bridge.send_signal,
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
        terminal_bridge.send_signal,
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
        success = await terminal_bridge.send_escape(session.tmux_session_name)
        if not success:
            logger.error("Failed to send ESCAPE to session %s", session.session_id[:8])
            return

        # Send second ESCAPE if double flag set
        if double:
            await asyncio.sleep(0.1)
            success = await terminal_bridge.send_escape(session.tmux_session_name)
            if not success:
                logger.error("Failed to send second ESCAPE to session %s", session.session_id[:8])
                return

        # Wait briefly for ESCAPE to register
        await asyncio.sleep(0.1)

        # Parse terminal size
        cols, rows = 80, 24
        if session.terminal_size and "x" in session.terminal_size:
            try:
                cols, rows = map(int, session.terminal_size.split("x"))
            except ValueError:
                pass

        # Check if process is running for polling decision
        is_process_running = await terminal_bridge.is_process_running(session.tmux_session_name)

        # Send text + ENTER
        success = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
            session_id=session.session_id,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
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
        terminal_bridge.send_escape,
        session,
    )

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        success = await _execute_control_key(
            terminal_bridge.send_escape,
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
        feedback_msg_id = await client.send_message(
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

        # Track feedback message
        await db.add_pending_deletion(session.session_id, feedback_msg_id)
        logger.debug(
            "Tracked feedback message %s for deletion (session %s)",
            feedback_msg_id,
            session.session_id[:8],
        )

        return

    # Get the key to send (first argument)
    key = args[0]

    # Send CTRL+key to the tmux session (TUI interaction, no polling)
    success = await _execute_control_key(
        terminal_bridge.send_ctrl_key,
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
        terminal_bridge.send_tab,
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
        terminal_bridge.send_shift_tab,
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
        terminal_bridge.send_backspace,
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
        terminal_bridge.send_enter,
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
        terminal_bridge.send_arrow_key,
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
        feedback_msg_id = await client.send_message(
            session, f"Session renamed to: {new_title}", metadata=MessageMetadata()
        )

        # Track feedback message for cleanup on next user input
        if feedback_msg_id:
            await db.add_pending_deletion(session.session_id, feedback_msg_id)
            logger.debug(
                "Tracked feedback message %s for deletion (session %s)",
                feedback_msg_id,
                session.session_id[:8],
            )
    else:
        logger.error("Failed to update channel title for session %s", session.session_id[:8])
        error_msg_id = await client.send_message(session, "Failed to update channel title", metadata=MessageMetadata())
        if error_msg_id:
            await db.add_pending_deletion(session.session_id, error_msg_id)


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
        help_msg_id = await client.send_message(session, response, MessageMetadata())
        if help_msg_id:
            await db.add_pending_deletion(session.session_id, help_msg_id)
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
    # Kill tmux session
    success = await terminal_bridge.kill_session(session.tmux_session_name)
    if success:
        logger.info("Killed tmux session %s", session.tmux_session_name)
    else:
        logger.warning("Failed to kill tmux session %s", session.tmux_session_name)

    # Delete from database
    await db.delete_session(session.session_id)
    logger.info("Deleted session %s from database", session.session_id[:8])

    # Clean up channels and workspace (shared logic)
    await cleanup_session_resources(session, client)


async def handle_end_session(
    session_id: str,
    client: "AdapterClient",
) -> dict[str, object]:
    """End a session - graceful termination for MCP tool.

    Similar to handle_exit_session but designed for MCP tool calls.
    Kills tmux, marks session closed, cleans up resources.

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

    if session.closed:
        return {
            "status": "error",
            "message": f"Session {session_id[:8]} already closed",
        }

    # Kill tmux session
    success = await terminal_bridge.kill_session(session.tmux_session_name)
    if success:
        logger.info("Killed tmux session %s", session.tmux_session_name)
    else:
        logger.warning("Failed to kill tmux session %s", session.tmux_session_name)
        return {
            "status": "error",
            "message": f"Failed to kill tmux session {session.tmux_session_name}",
        }

    # Mark as closed in database
    await db.update_session(session_id, closed=True)
    logger.info("Marked session %s as closed", session_id[:8])

    # Clean up channels and workspace (shared logic)
    await cleanup_session_resources(session, client)

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
        await client.send_feedback(session, f"Unknown agent: {agent_name}", MessageMetadata())
        return

    # Prefer per-session stored thinking_mode if user didn't specify one.
    ux_state = await db.get_ux_state(session.session_id)
    stored_mode_raw = ux_state.thinking_mode if ux_state and isinstance(ux_state.thinking_mode, str) else None
    stored_mode = stored_mode_raw or ThinkingMode.SLOW.value

    user_args = list(args)
    thinking_mode = stored_mode
    if user_args and user_args[0] in ThinkingMode._value2member_map_:
        thinking_mode = user_args.pop(0)

    if thinking_mode == ThinkingMode.DEEP.value and agent_name != AgentName.CODEX.value:
        await client.send_feedback(
            session,
            "deep is only supported for codex. Use fast/med/slow for other agents.",
            MessageMetadata(),
        )
        return

    start_args = AgentStartArgs(
        agent_name=agent_name,
        thinking_mode=ThinkingMode(thinking_mode),
        user_args=user_args,
    )

    # Persist chosen thinking_mode so subsequent MCP calls (or resumes) can reuse it.
    await db.update_ux_state(session.session_id, thinking_mode=start_args.thinking_mode.value)

    base_cmd = get_agent_command(start_args.agent_name, thinking_mode=start_args.thinking_mode.value)

    cmd_parts = [base_cmd]

    # Add any additional arguments from the user (prompt or flags)
    if start_args.user_args:
        quoted_args = [shlex.quote(arg) for arg in start_args.user_args]
        cmd_parts.extend(quoted_args)

    cmd = " ".join(cmd_parts)
    logger.info("Executing agent start command for %s: %s", agent_name, cmd)

    # Save active agent and clear previous native session bindings.
    await db.update_ux_state(
        session.session_id,
        active_agent=agent_name,
        native_session_id=None,
        native_log_file=None,
    )

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
    # Get UX state first - needed for both active_agent fallback and native_session_id
    ux_state = await db.get_ux_state(session.session_id)

    # If no agent_name provided, use active_agent from session
    if not agent_name:
        active = ux_state.active_agent if ux_state else None
        if not active:
            await client.send_feedback(session, "No active agent to resume", MessageMetadata())
            return
        agent_name = active

    agent_config = config.agents.get(agent_name)
    if not agent_config:
        await client.send_feedback(session, f"Unknown agent: {agent_name}", MessageMetadata())
        return

    thinking_raw = ux_state.thinking_mode if ux_state and isinstance(ux_state.thinking_mode, str) else None
    resume_args = AgentResumeArgs(
        agent_name=agent_name,
        native_session_id=ux_state.native_session_id if ux_state else None,
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

    # Save active agent to UX state
    await db.update_ux_state(session.session_id, active_agent=agent_name)

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
    ux_state = await db.get_ux_state(session.session_id)
    active_agent = ux_state.active_agent if ux_state else None
    native_session_id = ux_state.native_session_id if ux_state else None

    target_agent = agent_name or active_agent
    if not target_agent:
        await client.send_feedback(
            session,
            "❌ Cannot restart agent: no active agent for this session.",
            MessageMetadata(),
        )
        return

    if not native_session_id:
        await client.send_feedback(
            session,
            "❌ Cannot restart agent: no native session ID stored. Start the agent first.",
            MessageMetadata(),
        )
        return

    if not config.agents.get(target_agent):
        await client.send_feedback(session, f"❌ Unknown agent: {target_agent}", MessageMetadata())
        return

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id[:8],
        session.tmux_session_name,
    )

    # Kill any existing process (send CTRL+C twice).
    sent = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
    if sent:
        await asyncio.sleep(0.2)
        await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
        await asyncio.sleep(0.5)

    ready = await terminal_bridge.wait_for_shell_ready(session.tmux_session_name)
    if not ready:
        await client.send_feedback(
            session,
            "❌ Agent did not exit after SIGINT. Restart aborted.",
            MessageMetadata(),
        )
        return

    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=(ux_state.thinking_mode if ux_state and ux_state.thinking_mode else "slow"),
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
