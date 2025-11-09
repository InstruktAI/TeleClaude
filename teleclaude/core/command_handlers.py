"""Command handlers for TeleClaude bot commands.

Extracted from daemon.py to reduce file size and improve organization.
All handlers are stateless functions with explicit dependencies.
"""

import asyncio
import logging
import os
import shlex
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.models import Session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


# Type alias for start_polling function
StartPollingFunc = Callable[[str, str], Awaitable[None]]


# Shared helper for ALL command handlers - cleanup logic in ONE place
async def _execute_and_poll(  # type: ignore[explicit-any]
    terminal_action: Callable[..., Awaitable[bool]],
    session: Session,
    message_id: str | None,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
    *terminal_args: Any,
) -> bool:
    """Execute terminal action, cleanup messages on success, start polling.

    This is the SINGLE helper used by ALL command handlers (ctrl, cancel, escape, etc.)
    to avoid duplicating cleanup logic across handlers.

    Args:
        terminal_action: Terminal bridge function to execute
        session: Session object (contains session_id and tmux_session_name)
        message_id: Message ID to cleanup on success
        client: AdapterClient for message cleanup
        start_polling: Function to start output polling
        *terminal_args: Additional arguments for terminal_action (after tmux_session_name)

    Returns:
        True if terminal action succeeded, False otherwise
    """
    # Execute terminal action with session's tmux_session_name + any additional args
    success = await terminal_action(session.tmux_session_name, *terminal_args)

    if success:
        # NOTE: Message cleanup now handled by AdapterClient.handle_event()
        # Start polling for output
        await start_polling(session.session_id, session.tmux_session_name)

    return success


async def handle_create_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
) -> None:
    """Create a new terminal session.

    Args:
        context: Command context with adapter_type
        args: Command arguments (optional custom title)
        client: AdapterClient for channel operations
    """
    # Get adapter_type from context
    adapter_type = context.get("adapter_type")
    if not adapter_type:
        raise ValueError("Context missing adapter_type")

    computer_name = config.computer.name
    working_dir = os.path.expanduser(config.computer.default_working_dir)
    shell = config.computer.default_shell
    terminal_size = "120x40"  # Default terminal size

    # Generate tmux session name
    session_suffix = str(uuid.uuid4())[:8]
    tmux_name = f"{computer_name.lower()}-session-{session_suffix}"

    # Create topic first with custom title if provided
    if args and len(args) > 0:
        base_title = f"${computer_name} - {' '.join(args)}"
    else:
        base_title = f"${computer_name} - New session"

    # Check for duplicate titles and append number if needed
    title = base_title
    existing_sessions = await db.list_sessions()
    existing_titles = {s.title for s in existing_sessions if not s.closed}

    if title in existing_titles:
        counter = 2
        while f"{base_title} ({counter})" in existing_titles:
            counter += 1
        title = f"{base_title} ({counter})"

    # Create session in database first (need session_id for create_channel)
    session_id_new = str(uuid.uuid4())
    session = await db.create_session(
        computer_name=computer_name,
        tmux_session_name=tmux_name,
        origin_adapter=str(adapter_type),
        title=title,
        adapter_metadata={},
        terminal_size=terminal_size,
        working_directory=working_dir,
        session_id=session_id_new,
    )

    # Create channel via client (now we have a real session_id)
    channel_id = await client.create_channel(session_id=session_id_new, title=title, origin_adapter=str(adapter_type))

    # Update session with channel_id
    await db.update_session(session.session_id, adapter_metadata={"channel_id": channel_id})

    # Create actual tmux session
    cols, rows = map(int, terminal_size.split("x"))
    success = await terminal_bridge.create_tmux_session(
        name=tmux_name, shell=shell, working_dir=working_dir, cols=cols, rows=rows
    )

    if success:
        # Send welcome message to topic
        welcome = f"""Session created!

Computer: {computer_name}
Working directory: {working_dir}
Shell: {shell}

You can now send commands to this session.
"""
        await client.send_message(session.session_id, welcome)
        logger.info("Created session: %s", session.session_id)
    else:
        await db.delete_session(session.session_id)
        logger.error("Failed to create tmux session")


async def handle_list_sessions(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
) -> None:
    """List all active sessions.

    Args:
        context: Command context with adapter_type and message_thread_id
        client: AdapterClient for sending messages
    """
    # Get adapter from context
    adapter_type = context.get("adapter_type")
    if not adapter_type:
        logger.error("Cannot send general message - no adapter_type in context")
        return

    sessions = await db.list_sessions(closed=False)

    if not sessions:
        # Send to General topic
        await client.send_general_message(
            text="No active sessions.",
            adapter_type=str(adapter_type),
            metadata={"message_thread_id": context.get("message_thread_id")},
        )
        return

    # Build response
    lines = ["Active Sessions:\n"]
    for s in sessions:
        lines.append(
            f"• {s.title}\n" f"  ID: {s.session_id[:8]}...\n" f"  Created: {s.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        )

    response = "\n".join(lines)

    # Send to same topic where command was issued
    await client.send_general_message(
        text=response, adapter_type=str(adapter_type), metadata={"message_thread_id": context.get("message_thread_id")}
    )


async def handle_list_projects(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
) -> None:
    """List trusted project directories as JSON.

    For AI-to-AI sessions via Redis, returns JSON array of available project paths.

    Args:
        context: Command context with session_id
        client: AdapterClient for sending messages
    """
    import json

    # Get session_id from context (required for AI-to-AI sessions)
    session_id = context.get("session_id")
    if not session_id:
        logger.error("No session_id in context for list_projects")
        return

    # Get trusted_dirs and default_working_dir from config
    trusted_dirs = config.computer.trusted_dirs
    default_working_dir = config.computer.default_working_dir

    # Expand environment variables and filter existing paths
    all_dirs = []

    # Always include default_working_dir first if it exists
    if default_working_dir:
        expanded_default = os.path.expanduser(os.path.expandvars(default_working_dir))
        if Path(expanded_default).exists():
            all_dirs.append(expanded_default)

    # Add trusted_dirs (skip duplicates and non-existent paths)
    for dir_path in trusted_dirs:
        expanded = os.path.expanduser(os.path.expandvars(dir_path))
        if Path(expanded).exists() and expanded not in all_dirs:
            all_dirs.append(expanded)

    # Send as JSON array to the session's output stream
    await client.send_message(
        session_id=session_id,
        text=json.dumps(all_dirs),
        metadata={},
    )


async def handle_cancel_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send CTRL+C (SIGINT) to a session.

    Args:
        context: Command context with session_id
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        double: If True, send CTRL+C twice (for stubborn programs)
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in cancel command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Send SIGINT (CTRL+C) to the tmux session
    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_signal,
        session,
        message_id,
        client,
        start_polling,
        "SIGINT",
    )

    if double and success:
        # Wait a moment then send second SIGINT
        await asyncio.sleep(0.2)
        # Don't pass message_id for second signal (already deleted)
        success = await _execute_and_poll(
            terminal_bridge.send_signal,
            session,
            None,
            client,
            start_polling,
            "SIGINT",
        )

    if success:
        logger.info("Sent %s SIGINT to session %s", "double" if double else "single", session_id[:8])
    else:
        logger.error("Failed to send SIGINT to session %s", session_id[:8])


async def handle_kill_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Force kill foreground process with SIGKILL (guaranteed termination).

    Args:
        context: Command context with session_id
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in kill command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Send SIGKILL (forceful termination) to the tmux session
    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_signal,
        session,
        message_id,
        client,
        start_polling,
        "SIGKILL",
    )

    if success:
        logger.info("Sent SIGKILL to session %s (force kill)", session_id[:8])
    else:
        logger.error("Failed to send SIGKILL to session %s", session_id[:8])


async def handle_escape_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
    double: bool = False,
) -> None:
    """Send ESCAPE key to a session, optionally followed by text+ENTER.

    Args:
        context: Command context with session_id
        args: Optional text to send after ESCAPE (e.g., [":wq"] sends ESCAPE, then :wq+ENTER)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        double: If True, send ESCAPE twice before sending text (if any)
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in escape command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # If text provided: send ESCAPE (once or twice) + text+ENTER
    if args:
        text = " ".join(args)

        # Send ESCAPE first
        success = await terminal_bridge.send_escape(session.tmux_session_name)
        if not success:
            logger.error("Failed to send ESCAPE to session %s", session_id[:8])
            return

        # Send second ESCAPE if double flag set
        if double:
            await asyncio.sleep(0.1)
            success = await terminal_bridge.send_escape(session.tmux_session_name)
            if not success:
                logger.error("Failed to send second ESCAPE to session %s", session_id[:8])
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
        is_process_running = await db.is_polling(str(session_id))

        # Send text + ENTER
        success = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
            shell=config.computer.default_shell,
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=not is_process_running,
        )

        if not success:
            logger.error("Failed to send text to session %s", session_id[:8])
            return

        # Update activity
        await db.update_last_activity(str(session_id))

        # NOTE: Message cleanup now handled by AdapterClient.handle_event()

        # Start polling if needed
        if not is_process_running:
            await start_polling(str(session_id), session.tmux_session_name)

        logger.info("Sent %s ESCAPE + '%s' to session %s", "double" if double else "single", text, session_id[:8])
        return

    # No args: send ESCAPE only (support double)
    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_escape,
        session,
        message_id,
        client,
        start_polling,
    )

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        # Don't pass message_id for second escape (already deleted)
        success = await _execute_and_poll(
            terminal_bridge.send_escape,
            session,
            None,
            client,
            start_polling,
        )

    if success:
        logger.info("Sent %s ESCAPE to session %s", "double" if double else "single", session_id[:8])
    else:
        logger.error("Failed to send ESCAPE to session %s", session_id[:8])


async def handle_ctrl_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Send CTRL+key combination to a session.

    Args:
        context: Command context with session_id
        args: Command arguments (key to send with CTRL)
        client: AdapterClient for message operations
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in ctrl command context")
        return

    if not args:
        logger.warning("No key argument provided to ctrl command")
        feedback_msg_id = await client.send_message(str(session_id), "Usage: /ctrl <key> (e.g., /ctrl d for CTRL+D)")

        # Track both command message AND feedback message for deletion
        # Track command message (e.g., /ctrl)
        message_id = context.get("message_id")
        await db.add_pending_deletion(str(session_id), str(message_id))
        logger.debug("Tracked command message %s for deletion (session %s)", message_id, str(session_id)[:8])

        # Track feedback message
        await db.add_pending_deletion(str(session_id), feedback_msg_id)
        logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, str(session_id)[:8])

        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get the key to send (first argument)
    key = args[0]

    # Send CTRL+key to the tmux session
    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_ctrl_key,
        session,
        message_id,
        client,
        start_polling,
        key,
    )

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session_id[:8])
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session_id[:8])


async def handle_tab_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Send TAB key to a session.

    Args:
        context: Command context with session_id
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in tab command context")
        return

    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_tab,
        session,
        message_id,
        client,
        start_polling,
    )

    if success:
        logger.info("Sent TAB to session %s", session_id[:8])
    else:
        logger.error("Failed to send TAB to session %s", session_id[:8])


async def handle_shift_tab_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Send SHIFT+TAB key to a session.

    Args:
        context: Command context with session_id
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in shift_tab command context")
        return

    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_shift_tab,
        session,
        message_id,
        client,
        start_polling,
    )

    if success:
        logger.info("Sent SHIFT+TAB to session %s", session_id[:8])
    else:
        logger.error("Failed to send SHIFT+TAB to session %s", session_id[:8])


async def handle_arrow_key_command(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
    start_polling: StartPollingFunc,
    direction: str,
) -> None:
    """Send arrow key to a session with optional repeat count.

    Args:
        context: Command context with session_id
        args: Command arguments (optional repeat count)
        client: AdapterClient for message cleanup
        start_polling: Function to start polling for a session
        direction: Arrow direction ('up', 'down', 'left', 'right')
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in arrow key command context")
        return

    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

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

    message_id_obj = context.get("message_id")
    message_id = str(message_id_obj) if message_id_obj else None
    success = await _execute_and_poll(
        terminal_bridge.send_arrow_key,
        session,
        message_id,
        client,
        start_polling,
        direction,
        count,
    )

    if success:
        logger.info("Sent %s arrow key (x%d) to session %s", direction.upper(), count, session_id[:8])
    else:
        logger.error("Failed to send %s arrow key to session %s", direction.upper(), session_id[:8])


async def handle_resize_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
) -> None:
    """Resize terminal session.

    Args:
        context: Command context with session_id
        args: Command arguments (size preset or WxH format)
        client: AdapterClient for message operations
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in resize command context")
        return

    if not args:
        logger.warning("No size argument provided to resize command")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Size presets
    size_presets = {
        "small": "80x24",
        "medium": "120x40",
        "large": "160x60",
        "wide": "200x80",
    }

    # Get size (either preset name or direct WxH format)
    size_str = args[0].lower()
    size_str = size_presets.get(size_str, size_str)

    # Parse size
    try:
        cols, rows = map(int, size_str.split("x"))
    except ValueError:
        logger.error("Invalid size format: %s", size_str)
        await client.send_message(str(session_id), f"Invalid size format: {size_str}")
        return

    # Resize the tmux session
    success = await terminal_bridge.resize_session(session.tmux_session_name, cols, rows)

    if success:
        # Update session in database
        await db.update_session(str(session_id), terminal_size=size_str)
        logger.info("Resized session %s to %s", str(session_id)[:8], size_str)

        # NOTE: Message cleanup now handled by AdapterClient.handle_event()

        # Send feedback message
        feedback_msg_id = await client.send_message(str(session_id), f"Terminal resized to {size_str} ({cols}x{rows})")

        # Track feedback message for cleanup on next user input
        if feedback_msg_id:
            await db.add_pending_deletion(str(session_id), feedback_msg_id)
            logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, str(session_id)[:8])
    else:
        logger.error("Failed to resize session %s", str(session_id)[:8])
        await client.send_message(str(session_id), "Failed to resize terminal")


async def handle_rename_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
) -> None:
    """Rename session.

    Args:
        context: Command context with session_id
        args: Command arguments (new name)
        client: AdapterClient for message operations
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in rename command context")
        return

    if not args:
        logger.warning("No name argument provided to rename command")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Build new title with computer name prefix
    computer_name = config.computer.name
    new_title = f"[{computer_name}] {' '.join(args)}"

    # Update in database
    await db.update_session(str(session_id), title=new_title)

    # Update channel title via AdapterClient (looks up session internally)
    success = await client.update_channel_title(str(session_id), new_title)
    if success:
        logger.info("Renamed session %s to '%s'", str(session_id)[:8], new_title)

        # Cleanup old messages AND delete current command
        # NOTE: Message cleanup now handled by AdapterClient.handle_event()

        # Send feedback message
        feedback_msg_id = await client.send_message(str(session_id), f"Session renamed to: {new_title}")

        # Track feedback message for cleanup on next user input
        if feedback_msg_id:
            await db.add_pending_deletion(str(session_id), feedback_msg_id)
            logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, str(session_id)[:8])
    else:
        logger.error("Failed to update channel title for session %s", str(session_id)[:8])
        await client.send_message(str(session_id), "Failed to update channel title")


async def handle_cd_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    args: list[str],
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Change directory in session or list trusted directories.

    Args:
        context: Command context with session_id and message_id
        args: Command arguments (directory path or empty to list)
        client: AdapterClient for message operations
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in cd command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Strip whitespace from args and filter out empty strings
    args = [arg.strip() for arg in args if arg.strip()]

    # If no args, list trusted directories
    if not args:
        # Always prepend TC WORKDIR to the list
        trusted_dirs = ["TC WORKDIR"] + config.computer.trusted_dirs

        lines = ["**Trusted Directories:**\n"]
        for idx, dir_path in enumerate(trusted_dirs, 1):
            lines.append(f"{idx}. {dir_path}")

        response = "\n".join(lines)
        await client.send_message(str(session_id), response)
        return

    # Change to specified directory
    target_dir = " ".join(args)

    # Handle TC WORKDIR special case
    if target_dir == "TC WORKDIR":
        target_dir = os.path.expanduser(config.computer.default_working_dir)
    cd_command = f"cd {shlex.quote(target_dir)}"

    # Execute command and start polling
    message_id = str(context.get("message_id"))
    await execute_terminal_command(str(session_id), cd_command, True, message_id)


async def handle_exit_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    client: "AdapterClient",
    get_output_file: Callable[[str], Path],
) -> None:
    """Exit session - kill tmux session and delete topic.

    Args:
        context: Command context with session_id
        client: AdapterClient for channel operations
        get_output_file: Function to get output file path
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in exit command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Kill tmux session
    success = await terminal_bridge.kill_session(session.tmux_session_name)
    if success:
        logger.info("Killed tmux session %s", session.tmux_session_name)
    else:
        logger.warning("Failed to kill tmux session %s", session.tmux_session_name)

    # Delete from database
    await db.delete_session(str(session_id))
    logger.info("Deleted session %s from database", str(session_id)[:8])

    # Delete persistent output file
    try:
        output_file = get_output_file(str(session_id))
        if output_file.exists():
            output_file.unlink()
            logger.debug("Deleted output file for closed session %s", str(session_id)[:8])
    except Exception as e:
        logger.warning("Failed to delete output file: %s", e)

    # Delete channel/topic via AdapterClient (looks up session internally)
    success = await client.delete_channel(str(session_id))
    if success:
        logger.info("Deleted channel for session %s", session_id[:8])


async def handle_claude_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Start Claude Code in session.

    Args:
        context: Command context with session_id and message_id
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in claude command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Execute command and start polling
    message_id = str(context.get("message_id"))
    await execute_terminal_command(str(session_id), "claude --dangerously-skip-permissions", True, message_id)


async def handle_claude_resume_session(  # type: ignore[explicit-any]
    context: dict[str, Any],
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Resume Claude Code session using explicit session ID from metadata.

    Args:
        context: Command context with session_id and message_id
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in claude_resume command context")
        return

    # Get session
    session = await db.get_session(str(session_id))
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Check if session has stored Claude session ID and project_dir
    metadata = session.adapter_metadata or {}
    claude_session_id = metadata.get("claude_session_id")
    project_dir = metadata.get("project_dir")

    # Build command
    if claude_session_id and project_dir:
        # AI-managed session: cd to project + explicit session ID
        cmd = f"cd {shlex.quote(str(project_dir))} && claude --dangerously-skip-permissions --session-id {claude_session_id}"
    elif claude_session_id:
        # Has session ID but no project dir
        cmd = f"claude --dangerously-skip-permissions --session-id {claude_session_id}"
    else:
        # Human session: use --continue (current directory)
        cmd = "claude --dangerously-skip-permissions --continue"

    # Execute command and start polling
    message_id = str(context.get("message_id"))
    await execute_terminal_command(str(session_id), cmd, True, message_id)
