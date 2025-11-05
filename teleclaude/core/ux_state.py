"""Generic UX state management for system and session contexts.

Provides unified interface for storing/retrieving UX state in either:
- system_settings table (context='system') - global daemon state
- sessions table (context='session') - per-session state
"""

import json
import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UXStateContext(Enum):
    """Context for UX state storage."""

    SYSTEM = "system"
    SESSION = "session"


async def get_ux_state(db, context: UXStateContext, session_id: Optional[str] = None) -> dict:
    """Get UX state from database.

    Args:
        db: Database connection
        context: Whether to get system or session state
        session_id: Required if context is SESSION

    Returns:
        Dict with UX state (empty dict if not found)
    """
    try:
        if context == UXStateContext.SYSTEM:
            # Load from system_settings table
            cursor = await db.execute("SELECT value FROM system_settings WHERE key = 'ux_state'")
            row = await cursor.fetchone()
            if row:
                ux_state = json.loads(row[0])
                logger.debug("Loaded system UX state: %s", ux_state)
                return ux_state

            # Fall back to legacy registry_topic_id for backwards compatibility
            cursor = await db.execute("SELECT value FROM system_settings WHERE key = 'registry_topic_id'")
            row = await cursor.fetchone()
            if row:
                topic_id = int(row[0])
                logger.info("Migrating legacy registry_topic_id %s to ux_state", topic_id)
                return {"registry": {"topic_id": topic_id}}

            return {}

        elif context == UXStateContext.SESSION:
            if not session_id:
                raise ValueError("session_id required for SESSION context")

            # Load from sessions table
            cursor = await db.execute("SELECT ux_state FROM sessions WHERE session_id = ?", (session_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                ux_state = json.loads(row[0])
                logger.debug("Loaded session UX state for %s: %s", session_id[:8], ux_state)
                return ux_state

            # Fall back to legacy columns for backwards compatibility
            cursor = await db.execute(
                "SELECT output_message_id, idle_notification_message_id FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row and (row[0] or row[1]):
                logger.debug("Migrating legacy message IDs for session %s", session_id[:8])
                return {
                    "output_message_id": row[0],
                    "idle_notification_message_id": row[1],
                }

            return {}

    except Exception as e:
        logger.warning("Failed to retrieve UX state (context=%s): %s", context.value, e)
        return {}


async def update_ux_state(db, context: UXStateContext, updates: dict, session_id: Optional[str] = None):
    """Update UX state (merges with existing).

    Args:
        db: Database connection
        context: Whether to update system or session state
        updates: Dict with properties to update (deep merged with existing)
        session_id: Required if context is SESSION
    """
    try:
        # Load existing state
        existing_state = await get_ux_state(db, context, session_id)

        # Deep merge updates into existing state
        def deep_merge(base: dict, updates: dict) -> dict:
            """Recursively merge updates into base."""
            result = base.copy()
            for key, value in updates.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged_state = deep_merge(existing_state, updates)
        ux_state_json = json.dumps(merged_state)

        if context == UXStateContext.SYSTEM:
            # Store in system_settings table
            await db.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('ux_state', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (ux_state_json,),
            )
            await db.commit()
            logger.debug("Updated system UX state with: %s", updates)

        elif context == UXStateContext.SESSION:
            if not session_id:
                raise ValueError("session_id required for SESSION context")

            # Store in sessions table
            await db.execute(
                "UPDATE sessions SET ux_state = ? WHERE session_id = ?",
                (ux_state_json, session_id),
            )
            await db.commit()
            logger.debug("Updated session %s UX state with: %s", session_id[:8], updates)

    except Exception as e:
        logger.error("Failed to update UX state (context=%s): %s", context.value, e)
