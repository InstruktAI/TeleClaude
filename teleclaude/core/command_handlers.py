"""Command handlers for TeleClaude bot commands.

Extracted from daemon.py to reduce file size and improve organization.
All handlers are stateless functions with explicit dependencies.
"""

import asyncio
import functools
import logging
import os
import shlex
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypedDict, cast

import psutil

from teleclaude.config import config
from teleclaude.constants import (
    DEFAULT_CLAUDE_COMMAND,
    DEFAULT_CODEX_COMMAND,
    DEFAULT_GEMINI_COMMAND,
)
from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.events import EventContext
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.session_cleanup import (
    TMUX_SESSION_PREFIX,
    cleanup_session_resources,
)
from teleclaude.core.session_utils import ensure_unique_title
from teleclaude.core.voice_assignment import get_random_voice, get_voice_env_vars
from teleclaude.utils.claude_transcript import parse_claude_transcript

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


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
StartPollingFunc = Callable[[str, str, Optional[str]], Awaitable[None]]


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
) -> Callable[..., Awaitable[None]]:  # type: ignore[explicit-any]
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

    @functools.wraps(func)  # type: ignore[misc]
    async def wrapper(context: EventContext, *args: object, **kwargs: object) -> None:  # type: ignore[misc]
        # Extract session_id (let it crash if missing - our code emitted this event)
        # SystemCommandContext doesn't have session_id, but @with_session is only used for session-based commands
        assert hasattr(context, "session_id"), (
            f"Context {type(context).__name__} missing session_id"
        )
        session_id: str = str(context.session_id)  # type: ignore[misc]

        # Get session (let it crash if None - session should exist)
        session = await db.get_session(session_id)
        if session is None:
            raise RuntimeError(
                f"Session {session_id} not found - this should not happen"
            )

        # Call handler with session injected as first parameter
        await func(session, context, *args, **kwargs)

    return wrapper  # type: ignore[misc]


async def _execute_control_key(  # type: ignore[explicit-any]  # terminal_action has varying signatures
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
    working_dir = os.path.expanduser(config.computer.default_working_dir)
    terminal_size = "120x40"  # Default terminal size

    # For AI-to-AI sessions, use project_dir from metadata
    project_dir = metadata.project_dir
    if project_dir:
        working_dir = os.path.expanduser(project_dir)

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
            base_title = (
                f"AI:${initiator} > ${computer_name}[{short_project}] - New session"
            )
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

    # Extract claude_model from metadata if present (AI-initiated sessions)
    claude_model = metadata.claude_model if metadata else None

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
        claude_model=claude_model,
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
    voice_env_vars = get_voice_env_vars(voice) if voice else None
    success = await terminal_bridge.create_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        cols=cols,
        rows=rows,
        session_id=session_id,
        env_vars=voice_env_vars,
    )

    if success:
        # Send welcome feedback (temporary, auto-deleted on first user input)
        welcome = f"""Session created!

Computer: {computer_name}
Working directory: {working_dir}

You can now send commands to this session.
"""
        await client.send_feedback(session, welcome, MessageMetadata())
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

    return [
        {
            "session_id": s.session_id,
            "origin_adapter": s.origin_adapter,
            "title": s.title,
            "working_directory": s.working_directory,
            "status": "closed" if s.closed else "active",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_activity": s.last_activity.isoformat() if s.last_activity else None,
        }
        for s in sessions
    ]


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
        raise ValueError(
            "Computer configuration is incomplete - user, role, and host are required"
        )

    # Gather system stats
    memory = psutil.virtual_memory()  # type: ignore[misc]  # psutil has incomplete type stubs
    disk = psutil.disk_usage("/")  # type: ignore[misc]  # psutil has incomplete type stubs
    cpu_percent = psutil.cpu_percent(interval=0.1)  # type: ignore[misc]  # psutil has incomplete type stubs

    # Build typed system stats
    # Cast psutil values which have Any type stubs
    memory_total = cast(int, memory.total)  # type: ignore[misc]  # psutil has incomplete type stubs
    memory_available = cast(int, memory.available)  # type: ignore[misc]  # psutil has incomplete type stubs
    memory_percent = cast(float, memory.percent)  # type: ignore[misc]  # psutil has incomplete type stubs
    disk_total = cast(int, disk.total)  # type: ignore[misc]  # psutil has incomplete type stubs
    disk_free = cast(int, disk.free)  # type: ignore[misc]  # psutil has incomplete type stubs
    disk_percent = cast(float, disk.percent)  # type: ignore[misc]  # psutil has incomplete type stubs
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
    """Get session data from claude_session_file.

    Reads the Claude Code session file (JSONL format) and parses to markdown.
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

    session_id = str(context.session_id)  # type: ignore[misc]

    # Get session from database
    session = await db.get_session(session_id)
    if not session:
        logger.error("Session %s not found", session_id[:8])
        return {"status": "error", "error": "Session not found"}

    # Get ux_state to get claude_session_file
    ux_state = await db.get_ux_state(session_id)
    if not ux_state or not ux_state.claude_session_file:
        logger.error("No claude_session_file for session %s", session_id[:8])
        return {"status": "error", "error": "Session file not found"}

    claude_session_file = Path(ux_state.claude_session_file)
    if not claude_session_file.exists():
        logger.error("Claude session file does not exist: %s", claude_session_file)
        return {"status": "error", "error": "Session file does not exist"}

    # Parse Claude transcript to markdown with filtering
    try:
        markdown_content = parse_claude_transcript(
            str(claude_session_file),
            session.title,
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            tail_chars=tail_chars,
        )
        logger.info(
            "Parsed %d bytes of markdown for session %s",
            len(markdown_content),
            session_id[:8],
        )
    except Exception as e:
        logger.error("Failed to parse session file %s: %s", claude_session_file, e)
        return {"status": "error", "error": f"Failed to parse session file: {e}"}

    return {
        "status": "success",
        "session_id": session_id,
        "project_dir": session.working_directory,
        "messages": markdown_content,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": session.last_activity.isoformat()
        if session.last_activity
        else None,
    }


@with_session  # type: ignore[misc]
async def handle_cancel_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_kill_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_escape_command(  # type: ignore[misc]
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
                logger.error(
                    "Failed to send second ESCAPE to session %s", session.session_id[:8]
                )
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

        # Check if process is running for exit marker logic
        is_process_running = await db.is_polling(session.session_id)

        # Generate unique marker_id for exit detection (if appending marker)
        marker_id = None
        # Send text + ENTER (automatic exit marker decision)
        success, marker_id = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
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

        # Start polling if needed (pass marker_id for exit detection)
        if not is_process_running:
            await start_polling(
                session.session_id, session.tmux_session_name, marker_id
            )

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


@with_session  # type: ignore[misc]
async def handle_ctrl_command(  # type: ignore[misc]
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
        logger.error(
            "Failed to send CTRL+%s to session %s", key.upper(), session.session_id[:8]
        )


@with_session  # type: ignore[misc]
async def handle_tab_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_shift_tab_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_backspace_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_enter_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_arrow_key_command(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_rename_session(  # type: ignore[misc]
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
        logger.error(
            "Failed to update channel title for session %s", session.session_id[:8]
        )
        error_msg_id = await client.send_message(
            session, "Failed to update channel title", metadata=MessageMetadata()
        )
        if error_msg_id:
            await db.add_pending_deletion(session.session_id, error_msg_id)


@with_session  # type: ignore[misc]
async def handle_cd_session(  # type: ignore[misc]  # pylint: disable=too-many-locals  # Directory handling requires multiple variables
    session: Session,
    context: EventContext,
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Change directory in session or list trusted directories.

    Args:
        context: Command context with session_id and message_id
        args: Command arguments (directory path or empty to list)
        client: AdapterClient for message operations
        execute_terminal_command: Function to execute terminal command
    """

    # Strip whitespace from args and filter out empty strings
    args = [arg.strip() for arg in args if arg.strip()]

    # If no args, list trusted directories
    if not args:
        # Get all trusted dirs (includes TC WORKDIR from get_all_trusted_dirs)
        all_trusted_dirs = config.computer.get_all_trusted_dirs()

        lines = ["**Trusted Directories:**\n"]
        for idx, trusted_dir in enumerate(all_trusted_dirs, 1):
            # Show name - desc (if desc available)
            display_text = (
                f"{trusted_dir.name} - {trusted_dir.desc}"
                if trusted_dir.desc
                else trusted_dir.name
            )
            lines.append(f"{idx}. {display_text}")

        response = "\n".join(lines)
        help_msg_id = await client.send_message(session, response, MessageMetadata())
        if help_msg_id:
            await db.add_pending_deletion(session.session_id, help_msg_id)
        return

    # Change to specified directory
    target_dir = " ".join(args)

    # Handle TC WORKDIR special case
    if target_dir == "TC WORKDIR":
        target_dir = os.path.expanduser(config.computer.default_working_dir)
    cd_command = f"cd {shlex.quote(target_dir)}"

    # Execute command WITHOUT polling (cd is instant)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    success = await execute_terminal_command(
        session.session_id, cd_command, message_id, False
    )

    # Save working directory to DB if successful
    if success:
        await db.update_session(session.session_id, working_directory=target_dir)
        logger.debug(
            "Updated working_directory for session %s: %s",
            session.session_id[:8],
            target_dir,
        )


@with_session  # type: ignore[misc]
async def handle_exit_session(  # type: ignore[misc]
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


@with_session  # type: ignore[misc]
async def handle_claude_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    args: list[str],
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Start Claude Code in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to claude command)
        execute_terminal_command: Function to execute terminal command
    """
    # Get base command from config with fallback to constant
    # Strip whitespace to handle YAML literal blocks with trailing newlines
    base_cmd = (
        config.mcp.claude_command.strip()
        if config.mcp.claude_command
        else DEFAULT_CLAUDE_COMMAND
    )

    # Prepend --model flag if session has claude_model set (AI-initiated sessions)
    if session.claude_model:
        base_cmd = f"{base_cmd} --model={session.claude_model}"

    # Build command with args (properly quoted for shell)
    if args:
        # Use shlex.quote for proper shell escaping (handles !, $, ", ', etc.)
        quoted_args = shlex.quote(" ".join(args))
        cmd = f"{base_cmd} {quoted_args}"
    else:
        cmd = base_cmd

    # Execute command WITH polling (claude is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session  # type: ignore[misc]
async def handle_claude_resume_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Resume Claude Code session using explicit session ID from metadata.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        execute_terminal_command: Function to execute terminal command
    """
    # Check if session has stored Claude session ID and project_dir
    # Use getattr with default since not all adapter metadata types have these fields
    origin_meta = cast(
        object, getattr(session.adapter_metadata, session.origin_adapter, None)
    )
    claude_session_id = (
        cast(Optional[str], getattr(origin_meta, "claude_session_id", None))
        if origin_meta
        else None
    )
    project_dir_value = cast(
        Optional[str], getattr(origin_meta, "project_dir", None)
    ) or await terminal_bridge.get_current_directory(session.tmux_session_name)

    # Get base command from config with fallback to constant
    # Strip whitespace to handle YAML literal blocks with trailing newlines
    claude_cmd = (
        config.mcp.claude_command.strip()
        if config.mcp.claude_command
        else DEFAULT_CLAUDE_COMMAND
    )

    # Build command
    if claude_session_id:
        logger.info("Continuing claude session %s", claude_session_id)
        cmd = f"cd {shlex.quote(str(project_dir_value))} && {claude_cmd} --session-id {claude_session_id}"
    else:
        # Fresh session: use --continue to resume last claude session in current dir
        logger.info("Starting fresh claude session with --continue")
        cmd = f"{claude_cmd} --continue"

    # Execute command WITH polling (claude is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session  # type: ignore[misc]
async def handle_gemini_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    args: list[str],
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Start Gemini in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to gemini command)
        execute_terminal_command: Function to execute terminal command
    """
    # Get base command from config with fallback to constant
    base_cmd = (
        config.mcp.gemini_command.strip()
        if config.mcp.gemini_command
        else DEFAULT_GEMINI_COMMAND
    )

    # Build command with args (properly quoted for shell)
    if args:
        # Use shlex.quote for proper shell escaping (handles !, $, ", ', etc.)
        quoted_args = shlex.quote(" ".join(args))
        cmd = f"{base_cmd} {quoted_args}"
    else:
        cmd = base_cmd

    # Execute command WITH polling (gemini is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session  # type: ignore[misc]
async def handle_gemini_resume_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Resume Gemini session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        execute_terminal_command: Function to execute terminal command
    """
    # Get base command from config with fallback to constant
    gemini_cmd = (
        config.mcp.gemini_command.strip()
        if config.mcp.gemini_command
        else DEFAULT_GEMINI_COMMAND
    )

    # Assumption: Gemini supports --resume latest
    logger.info("Starting fresh gemini session with --resume latest")
    cmd = f"{gemini_cmd} --resume latest"

    # Execute command WITH polling (gemini is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session  # type: ignore[misc]
async def handle_codex_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    args: list[str],
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Start Codex in session with optional arguments.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        args: Command arguments (passed to codex command)
        execute_terminal_command: Function to execute terminal command
    """
    # Get base command from config with fallback to constant
    base_cmd = (
        config.mcp.codex_command.strip()
        if config.mcp.codex_command
        else DEFAULT_CODEX_COMMAND
    )

    # Build command with args (properly quoted for shell)
    if args:
        # Use shlex.quote for proper shell escaping (handles !, $, ", ', etc.)
        quoted_args = shlex.quote(" ".join(args))
        cmd = f"{base_cmd} {quoted_args}"
    else:
        cmd = base_cmd

    # Execute command WITH polling (codex is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)


@with_session  # type: ignore[misc]
async def handle_codex_resume_session(  # type: ignore[misc]
    session: Session,
    context: EventContext,
    execute_terminal_command: Callable[
        [str, str, Optional[str], bool], Awaitable[bool]
    ],
) -> None:
    """Resume Codex session.

    Args:
        session: Session object (injected by @with_session)
        context: Command context with message_id
        execute_terminal_command: Function to execute terminal command
    """
    # Get base command from config with fallback to constant
    codex_cmd = (
        config.mcp.codex_command.strip()
        if config.mcp.codex_command
        else DEFAULT_CODEX_COMMAND
    )

    # Assumption: Codex supports resume --last
    logger.info("Starting fresh codex session with resume --last")
    cmd = f"{codex_cmd} --resume last"

    # Execute command WITH polling (codex is long-running)
    message_id = str(getattr(context, "message_id", ""))  # type: ignore[misc]
    await execute_terminal_command(session.session_id, cmd, message_id, True)
