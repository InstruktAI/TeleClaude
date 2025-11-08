"""Terminal command execution orchestration.

Extracted from daemon.py to reduce file size and improve organization.
Handles command execution workflow with polling coordination.
"""

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.db import db

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


async def execute_terminal_command(
    session_id: str,
    command: str,
    client: "AdapterClient",  # AdapterClient instance
    start_polling: Callable[[str, str], Awaitable[None]],
    append_exit_marker: bool = True,
    message_id: str = None,
) -> bool:
    """Execute command in terminal and start polling if needed.

    Handles the common pattern of:
    1. Getting session
    2. Calling terminal.send_keys
    3. Storing exit_marker_appended
    4. Cleaning up command message
    5. Starting polling loop
    6. Sending error messages on failure

    Args:
        session_id: Session ID
        command: Command to execute
        client: AdapterClient instance for unified adapter operations
        start_polling: Function to start polling for session output
        append_exit_marker: Whether to append exit marker (default: True)
        message_id: Message ID to cleanup (optional)

    Returns:
        True if successful, False otherwise
    """
    # Get session
    session = await db.get_session(session_id)
    if not session:
        logger.error("Session %s not found", session_id[:8])
        return False

    # Get terminal size
    cols, rows = 80, 24
    if session.terminal_size and "x" in session.terminal_size:
        try:
            cols, rows = map(int, session.terminal_size.split("x"))
        except ValueError:
            pass

    # Send command
    success = await terminal_bridge.send_keys(
        session.tmux_session_name,
        command,
        shell=config.computer.default_shell,
        working_dir=session.working_directory,
        cols=cols,
        rows=rows,
        append_exit_marker=append_exit_marker,
    )

    if not success:
        await client.send_message(session_id, f"Failed to execute command: {command}")
        logger.error("Failed to execute command in session %s: %s", session_id[:8], command)
        return False

    # Update activity
    await db.update_last_activity(session_id)

    # Cleanup command message
    await db.cleanup_messages_after_success(session_id, message_id, client)

    # Start polling if exit marker was appended
    if append_exit_marker:
        await start_polling(session_id, session.tmux_session_name)

    logger.info("Executed command in session %s: %s", session_id[:8], command)
    return True
