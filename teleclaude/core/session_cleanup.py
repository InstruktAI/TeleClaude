"""Session cleanup utilities for handling stale sessions.

A session is considered stale when:
- It exists in the database as active (closed=False)
- But its tmux session no longer exists

This can happen when:
- User manually closes Telegram topic
- tmux session is killed externally
- Daemon crashes without proper cleanup
"""

import logging
import shutil
from typing import TYPE_CHECKING

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.session_utils import get_session_output_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


async def cleanup_stale_session(session_id: str, adapter_client: "AdapterClient") -> bool:
    """Clean up a single stale session.

    Args:
        session_id: Session identifier
        adapter_client: AdapterClient for deleting channels

    Returns:
        True if session was stale and cleaned up, False if session is healthy
    """
    session = await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found in database", session_id[:8])
        return False

    if session.closed:
        logger.debug("Session %s already marked as closed", session_id[:8])
        return False

    # Check if tmux session exists
    exists = await terminal_bridge.session_exists(session.tmux_session_name)
    if exists:
        # Session is healthy
        return False

    # Session is stale - tmux gone but DB says active
    logger.warning(
        "Found stale session %s (tmux %s no longer exists), cleaning up",
        session_id[:8],
        session.tmux_session_name,
    )

    # Mark as closed in database
    await db.update_session(session_id, closed=True)

    # Delete channel/topic in all adapters (forces sync across devices)
    try:
        await adapter_client.delete_channel(session)
        logger.info("Deleted channel for stale session %s", session_id[:8])
    except Exception as e:
        logger.warning("Failed to delete channel for stale session %s: %s", session_id[:8], e)

    # Clean up session workspace directory if exists (workspace/{session_id}/)
    workspace_dir = get_session_output_dir(session_id)
    if workspace_dir.exists():
        try:
            shutil.rmtree(workspace_dir)
            logger.debug("Deleted workspace directory for stale session %s", session_id[:8])
        except Exception as e:
            logger.warning("Failed to delete workspace for stale session %s: %s", session_id[:8], e)

    logger.info("Cleaned up stale session %s", session_id[:8])
    return True


async def cleanup_all_stale_sessions(adapter_client: "AdapterClient") -> int:
    """Find and clean up all stale sessions.

    Args:
        adapter_client: AdapterClient for deleting channels

    Returns:
        Number of stale sessions cleaned up
    """
    logger.info("Starting stale session cleanup scan")

    # Get all active sessions
    active_sessions = await db.get_active_sessions()

    if not active_sessions:
        logger.debug("No active sessions to check")
        return 0

    logger.info("Checking %d active sessions for staleness", len(active_sessions))

    cleaned_count = 0
    for session in active_sessions:
        was_stale = await cleanup_stale_session(session.session_id, adapter_client)
        if was_stale:
            cleaned_count += 1

    if cleaned_count > 0:
        logger.info("Cleaned up %d stale sessions", cleaned_count)
    else:
        logger.debug("No stale sessions found")

    return cleaned_count
