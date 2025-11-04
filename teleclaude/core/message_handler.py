"""Message handling for text input to terminal sessions.

Extracted from daemon.py to reduce file size and improve organization.
Handles text message processing, idle notification cleanup, and polling coordination.
"""

import logging
from typing import Any, Awaitable, Callable, Dict

from teleclaude.core import state_manager, terminal_bridge
from teleclaude.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


async def handle_message(
    session_id: str,
    text: str,
    context: Dict[str, Any],
    session_manager: SessionManager,
    config: Dict[str, Any],
    get_adapter_for_session: Callable[[str], Awaitable[Any]],
    start_polling: Callable[[str, str], Awaitable[None]],
) -> None:
    """Handle incoming text messages (commands for terminal).

    Args:
        session_id: Session ID
        text: Message text (command to execute)
        context: Platform-specific context
        session_manager: Session manager instance
        config: Application configuration
        get_adapter_for_session: Function to get adapter for session
        start_polling: Function to start polling for session output
    """
    logger.debug("Message for session %s: %s...", session_id[:8], text[:50])

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # Delete idle notification if one exists (user is interacting now)
    if state_manager.has_idle_notification(session_id):
        adapter = await get_adapter_for_session(session_id)
        notification_msg_id = state_manager.remove_idle_notification(session_id)
        await adapter.delete_message(session_id, notification_msg_id)
        logger.debug(
            "Deleted idle notification %s for session %s (user sent command)", notification_msg_id, session_id[:8]
        )

    # Strip leading // and replace with / (Telegram workaround - only at start of input)
    if text.startswith("//"):
        text = "/" + text[2:]
        logger.debug("Stripped leading // from user input, result: %s", text[:50])

    # Parse terminal size (e.g., "80x24" -> cols=80, rows=24)
    cols, rows = 80, 24
    if session.terminal_size and "x" in session.terminal_size:
        try:
            cols, rows = map(int, session.terminal_size.split("x"))
        except ValueError:
            pass

    # Check if a process is currently running (polling active)
    is_process_running = state_manager.is_polling(session_id)

    # Send command to terminal (will create fresh session if needed)
    # Only append exit marker if starting a NEW command, not sending input to running process
    success = await terminal_bridge.send_keys(
        session.tmux_session_name,
        text,
        shell=config["computer"]["default_shell"],
        working_dir=session.working_directory,
        cols=cols,
        rows=rows,
        append_exit_marker=not is_process_running,
    )

    adapter = await get_adapter_for_session(session_id)

    if not success:
        logger.error("Failed to send command to session %s", session_id[:8])
        await adapter.send_message(session_id, "Failed to send command to terminal")
        return

    # Track whether exit marker was appended
    state_manager.set_exit_marker(session_id, not is_process_running)

    # Update activity
    await session_manager.update_last_activity(session_id)
    await session_manager.increment_command_count(session_id)

    # Delete user message if polling is active (message gets absorbed as input)
    if is_process_running:
        # Get all pending deletions (feedback messages, previous user messages, etc.)
        pending_deletions = state_manager.get_pending_deletions(session_id)

        # Add current user message to deletions
        message_id = context.get("message_id")
        if message_id:
            pending_deletions.append(str(message_id))

        # Delete ALL messages underneath the output (feedback + user messages)
        for msg_id in pending_deletions:
            try:
                await adapter.delete_message(session_id, msg_id)
                logger.debug("Deleted message %s for session %s (cleanup)", msg_id, session_id[:8])
            except Exception as e:
                # Resilient to already-deleted messages (user manually deleted, etc.)
                logger.warning("Failed to delete message %s for session %s: %s", msg_id, session_id[:8], e)

        # Clear pending deletions after cleanup
        state_manager.clear_pending_deletions(session_id)

        # Don't start new poll - existing poll loop will capture the output
        logger.debug("Input sent to running process in session %s, existing poll will capture output", session_id[:8])
    else:
        # Start new poll loop for this command
        await start_polling(session_id, session.tmux_session_name)
