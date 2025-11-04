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
from typing import Any, Awaitable, Callable, Dict, List

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import get_config
from teleclaude.core import state_manager, terminal_bridge
from teleclaude.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


async def handle_create_session(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_by_type: Callable[[str], BaseAdapter],
) -> None:
    """Create a new terminal session.

    Args:
        context: Command context with adapter_type
        args: Command arguments (optional custom title)
        session_manager: Session manager instance
        get_adapter_by_type: Function to get adapter by type
    """
    # Get adapter_type from context
    adapter_type = context.get("adapter_type")
    if not adapter_type:
        raise ValueError("Context missing adapter_type")

    config = get_config()
    computer_name = config["computer"]["name"]
    working_dir = os.path.expanduser(config["computer"]["default_working_dir"])
    shell = config["computer"]["default_shell"]
    terminal_size = config["terminal"]["default_size"]

    # Generate tmux session name
    session_suffix = str(uuid.uuid4())[:8]
    tmux_name = f"{computer_name.lower()}-session-{session_suffix}"

    # Create topic first with custom title if provided
    if args and len(args) > 0:
        base_title = f"# {computer_name} - {' '.join(args)}"
    else:
        base_title = f"# {computer_name} - New session"

    # Check for duplicate titles and append number if needed
    title = base_title
    existing_sessions = await session_manager.list_sessions()
    existing_titles = {s.title for s in existing_sessions if s.status != "closed"}

    if title in existing_titles:
        counter = 2
        while f"{base_title} ({counter})" in existing_titles:
            counter += 1
        title = f"{base_title} ({counter})"

    # Get adapter and create channel
    adapter = get_adapter_by_type(adapter_type)
    channel_id = await adapter.create_channel(session_id="temp", title=title)

    # Create session in database
    session = await session_manager.create_session(
        computer_name=computer_name,
        tmux_session_name=tmux_name,
        adapter_type=adapter_type,
        title=title,
        adapter_metadata={"channel_id": channel_id},
        terminal_size=terminal_size,
        working_directory=working_dir,
    )

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
        await adapter.send_message(session.session_id, welcome)
        logger.info("Created session: %s", session.session_id)
    else:
        await session_manager.delete_session(session.session_id)
        logger.error("Failed to create tmux session")


async def handle_list_sessions(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_by_type: Callable[[str], BaseAdapter],
) -> None:
    """List all active sessions.

    Args:
        context: Command context with adapter_type and message_thread_id
        session_manager: Session manager instance
        get_adapter_by_type: Function to get adapter by type
    """
    # Get adapter from context
    adapter_type = context.get("adapter_type")
    if not adapter_type:
        logger.error("Cannot send general message - no adapter_type in context")
        return

    adapter = get_adapter_by_type(adapter_type)

    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        # Send to General topic
        await adapter.send_general_message(
            text="No active sessions.",
            metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "MarkdownV2"},
        )
        return

    # Build response
    lines = ["**Active Sessions:**\n"]
    for s in sessions:
        lines.append(
            f"• {s.title}\n" f"  ID: {s.session_id[:8]}...\n" f"  Created: {s.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        )

    response = "\n".join(lines)

    # Send to same topic where command was issued
    await adapter.send_general_message(
        text=response, metadata={"message_thread_id": context.get("message_thread_id"), "parse_mode": "MarkdownV2"}
    )


async def handle_cancel_command(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
    double: bool = False,
) -> None:
    """Send CTRL+C (SIGINT) to a session.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
        double: If True, send CTRL+C twice (for stubborn programs)
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in cancel command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Send SIGINT (CTRL+C) to the tmux session
    success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

    if double and success:
        # Wait a moment then send second SIGINT
        await asyncio.sleep(0.2)
        success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

    if success:
        logger.info("Sent %s SIGINT to session %s", "double" if double else "single", session_id[:8])
        # Poll for output (the terminal will show the ^C and any output from the interrupted command)
        await start_polling(session_id, session.tmux_session_name)
    else:
        logger.error("Failed to send SIGINT to session %s", session_id[:8])


async def handle_escape_command(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
    double: bool = False,
) -> None:
    """Send ESCAPE key to a session.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
        double: If True, send ESCAPE twice (for Vim, etc.)
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in escape command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Send ESCAPE to the tmux session
    success = await terminal_bridge.send_escape(session.tmux_session_name)

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        success = await terminal_bridge.send_escape(session.tmux_session_name)

    if success:
        logger.info("Sent %s ESCAPE to session %s", "double" if double else "single", session_id[:8])
        # Poll for output (the terminal will show any output from the escape action)
        await start_polling(session_id, session.tmux_session_name)
    else:
        logger.error("Failed to send ESCAPE to session %s", session_id[:8])


async def handle_ctrl_command(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
) -> None:
    """Send CTRL+key combination to a session.

    Args:
        context: Command context with session_id
        args: Command arguments (key to send with CTRL)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in ctrl command context")
        return

    if not args:
        logger.warning("No key argument provided to ctrl command")
        adapter = await get_adapter_for_session(session_id)
        feedback_msg_id = await adapter.send_message(session_id, "Usage: /ctrl <key> (e.g., /ctrl d for CTRL+D)")

        # Track both command message AND feedback message for deletion if process is running
        if state_manager.is_polling(session_id):
            # Track command message (e.g., /ctrl)
            command_msg_id = context.get("message_id")
            if command_msg_id:
                state_manager.add_pending_deletion(session_id, str(command_msg_id))
                logger.debug("Tracked command message %s for deletion (session %s)", command_msg_id, session_id[:8])

            # Track feedback message
            state_manager.add_pending_deletion(session_id, feedback_msg_id)
            logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, session_id[:8])

        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get the key to send (first argument)
    key = args[0]

    # Send CTRL+key to the tmux session
    success = await terminal_bridge.send_ctrl_key(session.tmux_session_name, key)

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session_id[:8])
        # Poll for output (the terminal will show any output from the ctrl action)
        await start_polling(session_id, session.tmux_session_name)
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session_id[:8])


async def handle_resize_session(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
) -> None:
    """Resize terminal session.

    Args:
        context: Command context with session_id
        args: Command arguments (size preset or WxH format)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in resize command context")
        return

    if not args:
        logger.warning("No size argument provided to resize command")
        return

    # Get session
    session = await session_manager.get_session(session_id)
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
        adapter = await get_adapter_for_session(session_id)
        await adapter.send_message(session_id, f"Invalid size format: {size_str}")
        return

    # Resize the tmux session
    success = await terminal_bridge.resize_session(session.tmux_session_name, cols, rows)

    # Get adapter for sending messages
    adapter = await get_adapter_for_session(session_id)

    if success:
        # Update session in database
        await session_manager.update_session(session_id, terminal_size=size_str)
        logger.info("Resized session %s to %s", session_id[:8], size_str)
        await adapter.send_message(session_id, f"Terminal resized to {size_str} ({cols}x{rows})")
    else:
        logger.error("Failed to resize session %s", session_id[:8])
        await adapter.send_message(session_id, "Failed to resize terminal")


async def handle_rename_session(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
) -> None:
    """Rename session.

    Args:
        context: Command context with session_id
        args: Command arguments (new name)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in rename command context")
        return

    if not args:
        logger.warning("No name argument provided to rename command")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Build new title with computer name prefix
    config = get_config()
    computer_name = config["computer"]["name"]
    new_title = f"[{computer_name}] {' '.join(args)}"

    # Update in database
    await session_manager.update_session(session_id, title=new_title)

    # Update channel title (topic_id for backward compat, channel_id is new standard)
    channel_id = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")
    if channel_id:
        adapter = await get_adapter_for_session(session_id)
        success = await adapter.update_channel_title(str(channel_id), new_title)
        if success:
            logger.info("Renamed session %s to '%s'", session_id[:8], new_title)
            await adapter.send_message(session_id, f"Session renamed to: {new_title}")
        else:
            logger.error("Failed to update channel title for session %s", session_id[:8])
            await adapter.send_message(session_id, "Failed to update channel title")
    else:
        logger.error("No channel_id for session %s", session_id[:8])


async def handle_cd_session(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    execute_terminal_command: Callable[[str, str, bool], Awaitable[bool]],
) -> None:
    """Change directory in session or list trusted directories.

    Args:
        context: Command context with session_id
        args: Command arguments (directory path or empty to list)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in cd command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get adapter for sending messages
    adapter = await get_adapter_for_session(session_id)

    # If no args, list trusted directories
    if not args:
        config = get_config()
        # Always prepend TC WORKDIR to the list
        trusted_dirs = ["TC WORKDIR"] + config.get("computer", {}).get("trustedDirs", [])

        lines = ["**Trusted Directories:**\n"]
        for idx, dir_path in enumerate(trusted_dirs, 1):
            lines.append(f"{idx}. {dir_path}")

        response = "\n".join(lines)
        await adapter.send_message(session_id, response)
        return

    # Change to specified directory
    target_dir = " ".join(args)

    # Handle TC WORKDIR special case
    config = get_config()
    if target_dir == "TC WORKDIR":
        target_dir = os.path.expanduser(config["computer"]["default_working_dir"])
    cd_command = f"cd {shlex.quote(target_dir)}"

    # Execute command and start polling
    await execute_terminal_command(session_id, cd_command, True)


async def handle_exit_session(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    get_output_file: Callable[[str], Path],
) -> None:
    """Exit session - kill tmux session and delete topic.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        get_output_file: Function to get output file path
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in exit command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get adapter
    adapter = await get_adapter_for_session(session_id)

    # Kill tmux session
    success = await terminal_bridge.kill_session(session.tmux_session_name)
    if success:
        logger.info("Killed tmux session %s", session.tmux_session_name)
    else:
        logger.warning("Failed to kill tmux session %s", session.tmux_session_name)

    # Delete from database
    await session_manager.delete_session(session_id)
    logger.info("Deleted session %s from database", session_id[:8])

    # Delete persistent output file
    try:
        output_file = get_output_file(session_id)
        if output_file.exists():
            output_file.unlink()
            logger.debug("Deleted output file for closed session %s", session_id[:8])
    except Exception as e:
        logger.warning("Failed to delete output file: %s", e)

    # Delete channel/topic
    channel_id = session.adapter_metadata.get("channel_id")
    if channel_id:
        await adapter.delete_channel(str(channel_id))
        logger.info("Deleted channel %s", channel_id)


async def handle_claude_session(
    context: Dict[str, Any],
    session_manager: SessionManager,
    execute_terminal_command: Callable[[str, str, bool], Awaitable[bool]],
) -> None:
    """Start Claude Code in session.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in claude command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Execute command and start polling
    await execute_terminal_command(session_id, "claude --dangerously-skip-permissions", True)


async def handle_claude_resume_session(
    context: Dict[str, Any],
    session_manager: SessionManager,
    execute_terminal_command: Callable[[str, str, bool], Awaitable[bool]],
) -> None:
    """Resume last Claude Code session (claude --continue).

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        execute_terminal_command: Function to execute terminal command
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in claude_resume command context")
        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Execute command and start polling
    await execute_terminal_command(session_id, "claude --dangerously-skip-permissions --continue", True)
