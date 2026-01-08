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
    def from_dict(cls, data: dict[str, object]) -> "SystemUXState":  # noqa: loose-dict - Deserialization input
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

    def to_dict(self) -> dict[str, object]:  # noqa: loose-dict - Serialization output
        """Convert to dict for JSON storage."""
        return {
            "registry": {
                "topic_id": self.registry.topic_id,
                "ping_message_id": self.registry.ping_message_id,
                "pong_message_id": self.registry.pong_message_id,
            }
        }


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
            data: dict[str, object] = data_raw  # noqa: loose-dict - Database JSON deserialization
            return SystemUXState.from_dict(data)

        return SystemUXState()

    except Exception as e:
        logger.warning("Failed to retrieve system UX state: %s", e)
        return SystemUXState()


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
