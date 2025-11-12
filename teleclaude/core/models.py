"""Data models for TeleClaude sessions."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class Session:
    """Represents a terminal session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    origin_adapter: str  # Single origin adapter (e.g., "redis" or "telegram")
    title: str
    adapter_metadata: Optional[dict[str, object]] = None  # Adapter-specific metadata
    closed: bool = False
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    terminal_size: str = "80x24"
    working_directory: str = "~"
    output_message_id: Optional[str] = None  # DEPRECATED: Use ux_state instead
    idle_notification_message_id: Optional[str] = None  # DEPRECATED: Use ux_state instead
    description: Optional[str] = None
    ux_state: Optional[str] = None  # JSON blob for session-level UX state

    def to_dict(self) -> dict[str, object]:
        """Convert session to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        # Convert adapter_metadata to JSON string for DB storage
        if self.adapter_metadata is not None:
            data["adapter_metadata"] = json.dumps(self.adapter_metadata)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":  # type: ignore[explicit-any]  # DB deserialization
        """Create session from dictionary (from database/JSON)."""
        # Parse datetime strings
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "last_activity" in data and isinstance(data["last_activity"], str):
            data["last_activity"] = datetime.fromisoformat(data["last_activity"])

        # Handle legacy adapter_type field (renamed to origin_adapter)
        if "adapter_type" in data:
            data["origin_adapter"] = data.pop("adapter_type")

        # Remove legacy status field (no longer exists)
        if "status" in data:
            del data["status"]

        # Remove legacy claude_session_file field (should be in ux_state JSON instead)
        if "claude_session_file" in data:
            del data["claude_session_file"]

        # Parse adapter_metadata JSON if stored as string
        if "adapter_metadata" in data and isinstance(data["adapter_metadata"], str):
            data["adapter_metadata"] = json.loads(data["adapter_metadata"])

        # Convert closed from SQLite integer (0/1) to Python bool
        if "closed" in data and isinstance(data["closed"], int):
            data["closed"] = bool(data["closed"])

        return cls(**data)


@dataclass
class Recording:
    """Represents a terminal recording file."""

    recording_id: Optional[int]
    session_id: str
    file_path: str
    recording_type: str  # 'text' or 'video'
    timestamp: Optional[datetime] = None

    def to_dict(self) -> dict[str, object]:
        """Convert recording to dictionary."""
        data = asdict(self)
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recording":  # type: ignore[explicit-any]  # DB deserialization
        """Create recording from dictionary (from database/JSON)."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
