"""Session lifecycle management - metadata migration and cleanup policies.

Extracted from daemon.py to reduce file size and improve organization.
All functions are stateless with explicit dependencies.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict

from teleclaude.core import terminal_bridge
from teleclaude.core.db import Db, db

logger = logging.getLogger(__name__)


async def migrate_session_metadata(session_manager: Db) -> None:
    """Migrate old session metadata to new format.

    Old format: {"topic_id": 12345}
    New format: {"channel_id": "12345"}

    Args:
        session_manager: Session manager instance
    """
    sessions = await db.list_sessions()
    migrated = 0

    for session in sessions:
        if not session.adapter_metadata:
            continue

        # Check if migration needed (has topic_id but not channel_id)
        if "topic_id" in session.adapter_metadata and "channel_id" not in session.adapter_metadata:
            # Migrate: rename topic_id to channel_id
            new_metadata = session.adapter_metadata.copy()
            new_metadata["channel_id"] = str(new_metadata.pop("topic_id"))

            # Serialize to JSON for database storage
            await db.update_session(session.session_id, adapter_metadata=json.dumps(new_metadata))
            migrated += 1
            logger.debug("Migrated session %s metadata", session.session_id[:8])

    if migrated > 0:
        logger.info("Migrated %d session(s) to new metadata format", migrated)


async def periodic_cleanup(session_manager: Db, cfg: "Config") -> None:  # type: ignore[name-defined]
    """Periodically clean up inactive sessions (72h lifecycle).

    Args:
        session_manager: Session manager instance
        cfg: Application configuration
    """
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await cleanup_inactive_sessions(session_manager, cfg)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic cleanup: %s", e)


async def cleanup_inactive_sessions(session_manager: Db, cfg: "Config") -> None:  # type: ignore[name-defined]
    """Clean up sessions inactive for 72+ hours.

    Args:
        session_manager: Session manager instance
        cfg: Application configuration
    """
    try:
        cutoff_time = datetime.now() - timedelta(hours=72)
        sessions = await db.list_sessions()

        for session in sessions:
            if session.closed:
                continue

            # Check last_activity timestamp
            if not session.last_activity:
                logger.warning("No last_activity for session %s", session.session_id[:8])
                continue

            if session.last_activity < cutoff_time:
                logger.info(
                    "Cleaning up inactive session %s (inactive for %s)",
                    session.session_id[:8],
                    datetime.now() - session.last_activity,
                )

                # Kill tmux session
                await terminal_bridge.kill_session(session.tmux_session_name)

                # Mark as closed
                await db.update_session(session.session_id, closed=True)

                logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

    except Exception as e:
        logger.error("Error cleaning up inactive sessions: %s", e)
