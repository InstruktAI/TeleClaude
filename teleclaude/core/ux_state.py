"""Generic UX state management for system and session contexts.

Provides unified interface for storing/retrieving UX state in either:
- system_settings table (context='system') - global daemon state
- sessions table (context='session') - per-session state
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

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
    pending_deletions: list[str] = field(default_factory=list)  # User input messages
    pending_feedback_deletions: list[str] = field(default_factory=list)  # Feedback messages
    last_input_adapter: Optional[str] = None  # Adapter that last received user input
    notification_sent: bool = False  # Agent notification hook flag
    native_session_id: Optional[str] = None  # Native agent session ID
    native_log_file: Optional[str] = None  # Path to native agent session .jsonl file
    active_agent: Optional[str] = None  # Name of the active agent (e.g. "claude", "gemini")
    thinking_mode: Optional[str] = None  # Model tier: "fast", "med", "slow" (MCP terminology)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionUXState":
        """Create SessionUXState from dict."""
        output_message_id_raw: object = data.get("output_message_id")
        pending_deletions_raw: object = data.get("pending_deletions", [])
        pending_feedback_deletions_raw: object = data.get("pending_feedback_deletions", [])
        last_input_adapter_raw: object = data.get("last_input_adapter")

        native_session_id_raw: object = data.get("native_session_id")
        native_log_file_raw: object = data.get("native_log_file")

        active_agent_raw: object = data.get("active_agent")
        thinking_mode_raw: object = data.get("thinking_mode")

        return cls(
            output_message_id=(str(output_message_id_raw) if output_message_id_raw else None),
            pending_deletions=(list(pending_deletions_raw) if isinstance(pending_deletions_raw, list) else []),
            pending_feedback_deletions=(
                list(pending_feedback_deletions_raw) if isinstance(pending_feedback_deletions_raw, list) else []
            ),
            last_input_adapter=(str(last_input_adapter_raw) if last_input_adapter_raw else None),
            notification_sent=bool(data.get("notification_sent", False)),
            native_session_id=(str(native_session_id_raw) if native_session_id_raw else None),
            native_log_file=str(native_log_file_raw) if native_log_file_raw else None,
            active_agent=str(active_agent_raw) if active_agent_raw else None,
            thinking_mode=str(thinking_mode_raw) if thinking_mode_raw else None,
        )

    def to_dict(self) -> dict[str, object]:
        """Convert to dict for JSON storage."""
        return {
            "output_message_id": self.output_message_id,
            "pending_deletions": self.pending_deletions,
            "pending_feedback_deletions": self.pending_feedback_deletions,
            "last_input_adapter": self.last_input_adapter,
            "notification_sent": self.notification_sent,
            "native_session_id": self.native_session_id,
            "native_log_file": self.native_log_file,
            "active_agent": self.active_agent,
            "thinking_mode": self.thinking_mode,
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
                topic_id=(int(registry_data["topic_id"]) if registry_data.get("topic_id") else None),
                ping_message_id=(
                    int(registry_data["ping_message_id"]) if registry_data.get("ping_message_id") else None
                ),
                pong_message_id=(
                    int(registry_data["pong_message_id"]) if registry_data.get("pong_message_id") else None
                ),
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
    pending_deletions: list[str] | object = _UNSET,
    pending_feedback_deletions: list[str] | object = _UNSET,
    last_input_adapter: Optional[str] | object = _UNSET,
    notification_sent: bool | object = _UNSET,
    native_session_id: Optional[str] | object = _UNSET,
    native_log_file: Optional[str] | object = _UNSET,
    active_agent: Optional[str] | object = _UNSET,
    thinking_mode: Optional[str] | object = _UNSET,
) -> None:
    """Update session UX state (merges with existing).

    Args:
        db: Database connection
        session_id: Session identifier
        output_message_id: Output message ID (optional)
        pending_deletions: List of user input message IDs pending deletion (optional)
        pending_feedback_deletions: List of feedback message IDs pending deletion (optional)
        last_input_adapter: Adapter that last received user input (optional)
        notification_sent: Whether Agent notification was sent (optional)
        native_session_id: Native agent session ID (optional)
        native_log_file: Path to native agent log file (optional)
        active_agent: Name of the active agent (optional)
    """
    try:
        # Load existing state
        existing = await get_session_ux_state(db, session_id)

        # Apply updates (only update fields that were provided)
        if output_message_id is not _UNSET:
            existing.output_message_id = output_message_id  # type: ignore
        if pending_deletions is not _UNSET:
            existing.pending_deletions = pending_deletions  # type: ignore
        if pending_feedback_deletions is not _UNSET:
            existing.pending_feedback_deletions = pending_feedback_deletions  # type: ignore
        if last_input_adapter is not _UNSET:
            existing.last_input_adapter = last_input_adapter  # type: ignore
        if notification_sent is not _UNSET:
            existing.notification_sent = notification_sent  # type: ignore
        if native_session_id is not _UNSET:
            existing.native_session_id = native_session_id  # type: ignore
        if native_log_file is not _UNSET:
            existing.native_log_file = native_log_file  # type: ignore
        if active_agent is not _UNSET:
            existing.active_agent = active_agent  # type: ignore
        if thinking_mode is not _UNSET:
            existing.thinking_mode = thinking_mode  # type: ignore

        # Store
        ux_state_json = json.dumps(existing.to_dict())
        await db.execute(
            "UPDATE sessions SET ux_state = ? WHERE session_id = ?",
            (ux_state_json, session_id),
        )
        await db.commit()
        logger.trace("Updated session %s UX state", session_id[:8])

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
