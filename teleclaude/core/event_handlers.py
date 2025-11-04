"""Platform event handlers.

Extracted from daemon.py to reduce file size and improve organization.
Handles adapter events like topic/channel closure.
"""

import logging
from typing import Any, Dict

from teleclaude.core import terminal_bridge
from teleclaude.core.session_manager import SessionManager

logger = logging.getLogger(__name__)


async def handle_topic_closed(
    session_id: str,
    context: Dict[str, Any],
    session_manager: SessionManager,
) -> None:
    """Handle topic/channel closure event.

    Args:
        session_id: Session ID
        context: Platform-specific context (includes topic_id, user_id, etc.)
        session_manager: Session manager instance
    """
    logger.info("Topic closed for session %s, closing session and tmux", session_id[:8])

    # Get session
    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning("Session %s not found during topic closure", session_id)
        return

    # Kill the tmux session
    tmux_session_name = session.tmux_session_name
    logger.info("Killing tmux session: %s", tmux_session_name)
    success = await terminal_bridge.kill_session(tmux_session_name)
    if not success:
        logger.warning("Failed to kill tmux session %s", tmux_session_name)

    # Mark session as closed in database
    await session_manager.update_session(session_id, closed=True)
    logger.info("Session %s marked as closed", session_id[:8])
