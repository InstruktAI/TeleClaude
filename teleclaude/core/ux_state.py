"""Generic UX state management for system and session contexts.

Provides unified interface for storing/retrieving UX state in either:
- system_settings table (context='system') - global daemon state
- sessions table (context='session') - per-session state
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Module-level DB connection (set by daemon on startup)
_db: Optional[aiosqlite.Connection] = None

# Sentinel value to distinguish "not provided" from None
_UNSET = object()


async def init(db_path: str) -> None:
    """Initialize ux_state module with database connection.

    Must be called once by daemon on startup.
    """
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row


class UXStateContext(Enum):
    """Context for UX state storage."""

    SYSTEM = "system"
    SESSION = "session"


@dataclass
class SessionUXState:
    """Typed UX state for sessions."""

    output_message_id: Optional[str] = None
    polling_active: bool = False
    pending_deletions: list[str] = field(default_factory=list)  # User input messages
    pending_feedback_deletions: list[str] = field(default_factory=list)  # Feedback messages
    notification_sent: bool = False  # Claude Code notification hook flag
    claude_session_id: Optional[str] = None  # Claude Code session ID
    claude_session_file: Optional[str] = None  # Path to native Claude Code session .jsonl file

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionUXState":
        """Create SessionUXState from dict."""
        output_message_id_raw: object = data.get("output_message_id")
        pending_deletions_raw: object = data.get("pending_deletions", [])
        pending_feedback_deletions_raw: object = data.get("pending_feedback_deletions", [])
        claude_session_id_raw: object = data.get("claude_session_id")
        claude_session_file_raw: object = data.get("claude_session_file")

        return cls(
            output_message_id=str(output_message_id_raw) if output_message_id_raw else None,
            polling_active=bool(data.get("polling_active", False)),
            pending_deletions=list(pending_deletions_raw) if isinstance(pending_deletions_raw, list) else [],
            pending_feedback_deletions=(
                list(pending_feedback_deletions_raw) if isinstance(pending_feedback_deletions_raw, list) else []
            ),
            notification_sent=bool(data.get("notification_sent", False)),
            claude_session_id=str(claude_session_id_raw) if claude_session_id_raw else None,
            claude_session_file=str(claude_session_file_raw) if claude_session_file_raw else None,
        )

    def to_dict(self) -> dict[str, object]:
        """Convert to dict for JSON storage."""
        return {
            "output_message_id": self.output_message_id,
            "polling_active": self.polling_active,
            "pending_deletions": self.pending_deletions,
            "pending_feedback_deletions": self.pending_feedback_deletions,
            "notification_sent": self.notification_sent,
            "claude_session_id": self.claude_session_id,
            "claude_session_file": self.claude_session_file,
        }


@dataclass
class RegistryState:
    """Registry state within system UX state."""

    topic_id: Optional[int] = None
    ping_message_id: Optional[int] = None
    pong_message_id: Optional[int] = None


@dataclass
class SystemUXState:
    """Typed UX state for system."""

    registry: RegistryState = field(default_factory=RegistryState)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SystemUXState":
        """Create SystemUXState from dict."""
        registry_data = data.get("registry", {})
        if isinstance(registry_data, dict):
            registry = RegistryState(
                topic_id=int(registry_data["topic_id"]) if registry_data.get("topic_id") else None,
                ping_message_id=int(registry_data["ping_message_id"]) if registry_data.get("ping_message_id") else None,
                pong_message_id=int(registry_data["pong_message_id"]) if registry_data.get("pong_message_id") else None,
            )
        else:
            registry = RegistryState()
        return cls(registry=registry)

    def to_dict(self) -> dict[str, object]:
        """Convert to dict for JSON storage."""
        return {
            "registry": {
                "topic_id": self.registry.topic_id,
                "ping_message_id": self.registry.ping_message_id,
                "pong_message_id": self.registry.pong_message_id,
            }
        }


async def get_session_ux_state(db: aiosqlite.Connection, session_id: str) -> SessionUXState:
    """Get typed UX state for session.

    Args:
        db: Database connection
        session_id: Session identifier

    Returns:
        SessionUXState (with defaults if not found)
    """
    try:
        # Load from sessions table
        cursor = await db.execute("SELECT ux_state FROM sessions WHERE session_id = ?", (session_id,))
        row = await cursor.fetchone()
        if row and row[0]:  # type: ignore[misc]  # Row access is Any from aiosqlite
            data_raw: object = json.loads(row[0])  # type: ignore[misc]  # Row access is Any from aiosqlite
            if not isinstance(data_raw, dict):
                logger.warning("Invalid ux_state format for session %s", session_id[:8])
                return SessionUXState()
            data: dict[str, object] = data_raw
            logger.debug("Loaded session UX state for %s: %s", session_id[:8], data)
            return SessionUXState.from_dict(data)

        return SessionUXState()

    except Exception as e:
        logger.warning("Failed to retrieve session UX state: %s", e)
        return SessionUXState()


async def get_system_ux_state(db: aiosqlite.Connection) -> SystemUXState:
    """Get typed UX state for system.

    Args:
        db: Database connection

    Returns:
        SystemUXState (with defaults if not found)
    """
    try:
        # Load from system_settings table
        cursor = await db.execute("SELECT value FROM system_settings WHERE key = 'ux_state'")
        row = await cursor.fetchone()
        if row:
            data_raw: object = json.loads(row[0])  # type: ignore[misc]  # Row access is Any from aiosqlite
            if not isinstance(data_raw, dict):
                logger.warning("Invalid system ux_state format")
                return SystemUXState()
            data: dict[str, object] = data_raw
            logger.debug("Loaded system UX state: %s", data)
            return SystemUXState.from_dict(data)

        return SystemUXState()

    except Exception as e:
        logger.warning("Failed to retrieve system UX state: %s", e)
        return SystemUXState()


async def update_session_ux_state(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # UX state has many optional fields
    db: aiosqlite.Connection,
    session_id: str,
    *,
    output_message_id: Optional[str] | object = _UNSET,
    polling_active: bool | object = _UNSET,
    pending_deletions: list[str] | object = _UNSET,
    pending_feedback_deletions: list[str] | object = _UNSET,
    notification_sent: bool | object = _UNSET,
    claude_session_id: Optional[str] | object = _UNSET,
    claude_session_file: Optional[str] | object = _UNSET,
) -> None:
    """Update session UX state (merges with existing).

    Args:
        db: Database connection
        session_id: Session identifier
        output_message_id: Output message ID (optional)
        polling_active: Whether polling is active (optional)
        pending_deletions: List of user input message IDs pending deletion (optional)
        pending_feedback_deletions: List of feedback message IDs pending deletion (optional)
        notification_sent: Whether Claude Code notification was sent (optional)
        claude_session_id: Claude Code session ID (optional)
        claude_session_file: Path to native Claude Code session file (optional)
    """
    try:
        # Load existing state
        existing = await get_session_ux_state(db, session_id)

        # Apply updates (only update fields that were provided)
        if output_message_id is not _UNSET:
            existing.output_message_id = output_message_id  # type: ignore
        if polling_active is not _UNSET:
            existing.polling_active = polling_active  # type: ignore
        if pending_deletions is not _UNSET:
            existing.pending_deletions = pending_deletions  # type: ignore
        if pending_feedback_deletions is not _UNSET:
            existing.pending_feedback_deletions = pending_feedback_deletions  # type: ignore
        if notification_sent is not _UNSET:
            existing.notification_sent = notification_sent  # type: ignore
        if claude_session_id is not _UNSET:
            existing.claude_session_id = claude_session_id  # type: ignore
        if claude_session_file is not _UNSET:
            existing.claude_session_file = claude_session_file  # type: ignore

        # Store
        ux_state_json = json.dumps(existing.to_dict())
        await db.execute(
            "UPDATE sessions SET ux_state = ? WHERE session_id = ?",
            (ux_state_json, session_id),
        )
        await db.commit()
        logger.debug("Updated session %s UX state", session_id[:8])

    except Exception as e:
        logger.error("Failed to update session UX state: %s", e)


async def update_system_ux_state(
    db: aiosqlite.Connection,
    *,
    registry_topic_id: Optional[int] | object = _UNSET,
    registry_ping_message_id: Optional[int] | object = _UNSET,
    registry_pong_message_id: Optional[int] | object = _UNSET,
) -> None:
    """Update system UX state (merges with existing).

    Args:
        db: Database connection
        registry_topic_id: Registry topic ID (optional)
        registry_ping_message_id: Registry ping message ID (optional)
        registry_pong_message_id: Registry pong message ID (optional)
    """
    try:
        # Load existing state
        existing = await get_system_ux_state(db)

        # Apply updates (only update fields that were provided)
        if registry_topic_id is not _UNSET:
            existing.registry.topic_id = registry_topic_id  # type: ignore
        if registry_ping_message_id is not _UNSET:
            existing.registry.ping_message_id = registry_ping_message_id  # type: ignore
        if registry_pong_message_id is not _UNSET:
            existing.registry.pong_message_id = registry_pong_message_id  # type: ignore

        # Store
        ux_state_json = json.dumps(existing.to_dict())
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
        logger.debug("Updated system UX state")

    except Exception as e:
        logger.error("Failed to update system UX state: %s", e)
