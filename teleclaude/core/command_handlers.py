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
from typing import Any, Awaitable, Callable, Dict, List, Optional

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import get_config
from teleclaude.core import terminal_bridge
from teleclaude.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


# Shared helper for ALL command handlers - cleanup logic in ONE place
async def _execute_and_poll(
    terminal_action: Callable[..., Awaitable[bool]],
    session: Any,  # Session object
    message_id: Optional[str],
    adapter: Any,
    start_polling: Callable[[str, str], Awaitable[None]],
    session_manager: SessionManager,
    *terminal_args: Any,
) -> bool:
    """Execute terminal action, cleanup messages on success, start polling.

    This is the SINGLE helper used by ALL command handlers (ctrl, cancel, escape, etc.)
    to avoid duplicating cleanup logic across handlers.

    Args:
        terminal_action: Terminal bridge function to execute
        session: Session object (contains session_id and tmux_session_name)
        message_id: Message ID to cleanup on success
        adapter: Chat adapter for message cleanup
        start_polling: Function to start output polling
        session_manager: Session manager instance
        *terminal_args: Additional arguments for terminal_action (after tmux_session_name)

    Returns:
        True if terminal action succeeded, False otherwise
    """
    # Execute terminal action with session's tmux_session_name + any additional args
    success = await terminal_action(session.tmux_session_name, *terminal_args)

    if success:
        # Cleanup pending messages (only if process running)
        await session_manager.cleanup_messages_after_success(session.session_id, message_id, adapter)
        # Start polling for output
        await start_polling(session.session_id, session.tmux_session_name)

    return success


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
        base_title = f"${computer_name} - {' '.join(args)}"
    else:
        base_title = f"${computer_name} - New session"

    # Check for duplicate titles and append number if needed
    title = base_title
    existing_sessions = await session_manager.list_sessions()
    existing_titles = {s.title for s in existing_sessions if not s.closed}

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

    sessions = await session_manager.list_sessions(closed=False)

    if not sessions:
        # Send to General topic
        await adapter.send_general_message(
            text="No active sessions.", metadata={"message_thread_id": context.get("message_thread_id")}
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
    await adapter.send_general_message(text=response, metadata={"message_thread_id": context.get("message_thread_id")})


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

    # Get adapter for cleanup
    adapter = await get_adapter_for_session(session_id)

    # Send SIGINT (CTRL+C) to the tmux session
    success = await _execute_and_poll(
        terminal_bridge.send_signal,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
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
            adapter,
            start_polling,
            session_manager,
            "SIGINT",
        )

    if success:
        logger.info("Sent %s SIGINT to session %s", "double" if double else "single", session_id[:8])
    else:
        logger.error("Failed to send SIGINT to session %s", session_id[:8])


async def handle_escape_command(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
    double: bool = False,
) -> None:
    """Send ESCAPE key to a session, optionally followed by text+ENTER.

    Args:
        context: Command context with session_id
        args: Optional text to send after ESCAPE (e.g., [":wq"] sends ESCAPE, then :wq+ENTER)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
        double: If True, send ESCAPE twice before sending text (if any)
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

    # Get adapter for cleanup
    adapter = await get_adapter_for_session(session_id)

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
        is_process_running = await session_manager.is_polling(session_id)

        # Send text + ENTER
        config = get_config()
        success = await terminal_bridge.send_keys(
            session.tmux_session_name,
            text,
            shell=config["computer"]["default_shell"],
            working_dir=session.working_directory,
            cols=cols,
            rows=rows,
            append_exit_marker=not is_process_running,
        )

        if not success:
            logger.error("Failed to send text to session %s", session_id[:8])
            return

        # Update activity
        await session_manager.update_last_activity(session_id)

        # Cleanup messages
        await session_manager.cleanup_messages_after_success(
            session_id,
            context.get("message_id"),
            adapter,
        )

        # Start polling if needed
        if not is_process_running:
            await start_polling(session_id, session.tmux_session_name)

        logger.info("Sent %s ESCAPE + '%s' to session %s", "double" if double else "single", text, session_id[:8])
        return

    # No args: send ESCAPE only (support double)
    success = await _execute_and_poll(
        terminal_bridge.send_escape,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
    )

    if double and success:
        # Wait a moment then send second ESCAPE
        await asyncio.sleep(0.2)
        # Don't pass message_id for second escape (already deleted)
        success = await _execute_and_poll(
            terminal_bridge.send_escape,
            session,
            None,
            adapter,
            start_polling,
            session_manager,
        )

    if success:
        logger.info("Sent %s ESCAPE to session %s", "double" if double else "single", session_id[:8])
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

        # Track both command message AND feedback message for deletion
        # Track command message (e.g., /ctrl)
        message_id = context.get("message_id")
        await session_manager.add_pending_deletion(session_id, message_id)
        logger.debug("Tracked command message %s for deletion (session %s)", message_id, session_id[:8])

        # Track feedback message
        await session_manager.add_pending_deletion(session_id, feedback_msg_id)
        logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, session_id[:8])

        return

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Get the key to send (first argument)
    key = args[0]

    # Get adapter and message ID for cleanup
    adapter = await get_adapter_for_session(session_id)

    # Send CTRL+key to the tmux session
    success = await _execute_and_poll(
        terminal_bridge.send_ctrl_key,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
        key,
    )

    if success:
        logger.info("Sent CTRL+%s to session %s", key.upper(), session_id[:8])
    else:
        logger.error("Failed to send CTRL+%s to session %s", key.upper(), session_id[:8])


async def handle_tab_command(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
) -> None:
    """Send TAB key to a session.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in tab command context")
        return

    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    adapter = await get_adapter_for_session(session_id)

    success = await _execute_and_poll(
        terminal_bridge.send_tab,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
    )

    if success:
        logger.info("Sent TAB to session %s", session_id[:8])
    else:
        logger.error("Failed to send TAB to session %s", session_id[:8])


async def handle_shift_tab_command(
    context: Dict[str, Any],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
) -> None:
    """Send SHIFT+TAB key to a session.

    Args:
        context: Command context with session_id
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in shift_tab command context")
        return

    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    adapter = await get_adapter_for_session(session_id)

    success = await _execute_and_poll(
        terminal_bridge.send_shift_tab,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
    )

    if success:
        logger.info("Sent SHIFT+TAB to session %s", session_id[:8])
    else:
        logger.error("Failed to send SHIFT+TAB to session %s", session_id[:8])


async def handle_arrow_key_command(
    context: Dict[str, Any],
    args: List[str],
    session_manager: SessionManager,
    get_adapter_for_session: Callable[[str], Awaitable[BaseAdapter]],
    start_polling: Callable[[str, str], Awaitable[None]],
    direction: str,
) -> None:
    """Send arrow key to a session with optional repeat count.

    Args:
        context: Command context with session_id
        args: Command arguments (optional repeat count)
        session_manager: Session manager instance
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for a session
        direction: Arrow direction ('up', 'down', 'left', 'right')
    """
    session_id = context.get("session_id")
    if not session_id:
        logger.warning("No session_id in arrow key command context")
        return

    session = await session_manager.get_session(session_id)
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

    adapter = await get_adapter_for_session(session_id)

    success = await _execute_and_poll(
        terminal_bridge.send_arrow_key,
        session,
        context.get("message_id"),
        adapter,
        start_polling,
        session_manager,
        direction,
        count,
    )

    if success:
        logger.info("Sent %s arrow key (x%d) to session %s", direction.upper(), count, session_id[:8])
    else:
        logger.error("Failed to send %s arrow key to session %s", direction.upper(), session_id[:8])


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

        # Cleanup old messages AND delete current command
        await session_manager.cleanup_messages_after_success(session_id, context.get("message_id"), adapter)

        # Send feedback message
        feedback_msg_id = await adapter.send_message(session_id, f"Terminal resized to {size_str} ({cols}x{rows})")

        # Track feedback message for cleanup on next user input
        if feedback_msg_id:
            await session_manager.add_pending_deletion(session_id, feedback_msg_id)
            logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, session_id[:8])
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

            # Cleanup old messages AND delete current command
            await session_manager.cleanup_messages_after_success(session_id, context.get("message_id"), adapter)

            # Send feedback message
            feedback_msg_id = await adapter.send_message(session_id, f"Session renamed to: {new_title}")

            # Track feedback message for cleanup on next user input
            if feedback_msg_id:
                await session_manager.add_pending_deletion(session_id, feedback_msg_id)
                logger.debug("Tracked feedback message %s for deletion (session %s)", feedback_msg_id, session_id[:8])
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
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Change directory in session or list trusted directories.

    Args:
        context: Command context with session_id and message_id
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
    message_id = str(context.get("message_id"))
    await execute_terminal_command(session_id, cd_command, True, message_id)


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
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Start Claude Code in session.

    Args:
        context: Command context with session_id and message_id
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
    message_id = str(context.get("message_id"))
    await execute_terminal_command(session_id, "claude --dangerously-skip-permissions", True, message_id)


async def handle_claude_resume_session(
    context: Dict[str, Any],
    session_manager: SessionManager,
    execute_terminal_command: Callable[[str, str, bool, str], Awaitable[bool]],
) -> None:
    """Resume last Claude Code session (claude --continue).

    Args:
        context: Command context with session_id and message_id
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
    message_id = str(context.get("message_id"))
    await execute_terminal_command(session_id, "claude --dangerously-skip-permissions --continue", True, message_id)
