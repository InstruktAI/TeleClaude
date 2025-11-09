"""Message handling for text input to terminal sessions.

Extracted from daemon.py to reduce file size and improve organization.
Handles text message processing, idle notification cleanup, and polling coordination.
"""

import logging
from typing import Any, Awaitable, Callable

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db

logger = logging.getLogger(__name__)


async def handle_message(  # type: ignore[explicit-any]
    session_id: str,
    text: str,
    context: dict[str, Any],
    client: "AdapterClient",  # AdapterClient instance
    start_polling: Callable[[str, str], Awaitable[None]],
) -> None:
    """Handle incoming text messages (commands for terminal).

    Args:
        session_id: Session ID
        text: Message text (command to execute)
        context: Platform-specific context
        client: AdapterClient instance for unified adapter operations
        start_polling: Function to start polling for session output
    """
    logger.debug("Message for session %s: %s...", session_id[:8], text[:50])

    # Get session
    session = await db.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    # NOTE: Idle notification cleanup now handled by AdapterClient._cleanup_previous_interaction()

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
    # Use ux_state from DB as source of truth (survives daemon restarts)
    ux_state = await db.get_ux_state(session_id)
    is_process_running = ux_state.polling_active

    # Send command to terminal (will create fresh session if needed)
    # Only append exit marker if starting a NEW command, not sending input to running process
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
        logger.error("Failed to send command to session %s", session_id[:8])
        await client.send_message(session_id, "Failed to send command to terminal")
        return

    # Update activity
    await db.update_last_activity(session_id)

    # NOTE: Message tracking/cleanup now handled by AdapterClient.handle_event()
    # - Previous messages cleaned up BEFORE handler (in _cleanup_previous_interaction)
    # - Current message tracked AFTER handler (in handle_event POST step)

    # Start new poll if process not running, otherwise existing poll continues
    if not is_process_running:
        await start_polling(session_id, session.tmux_session_name)
    else:
        logger.debug("Input sent to running process in session %s, existing poll will capture output", session_id[:8])
