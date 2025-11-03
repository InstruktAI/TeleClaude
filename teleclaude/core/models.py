"""Data models for TeleClaude sessions and recordings."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Session:
    """Represents a terminal session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    adapter_type: str
    title: Optional[str] = None
    adapter_metadata: Optional[Dict[str, Any]] = None
    status: str = "active"
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    terminal_size: str = "80x24"
    working_directory: str = "~"
    command_count: int = 0
    output_message_id: Optional[str] = None
    idle_notification_message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        # Convert adapter_metadata to JSON string for DB storage
        if self.adapter_metadata:
            data["adapter_metadata"] = json.dumps(self.adapter_metadata)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create session from dictionary."""
        # Parse datetime strings
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "last_activity" in data and isinstance(data["last_activity"], str):
            data["last_activity"] = datetime.fromisoformat(data["last_activity"])
        # Parse adapter_metadata JSON
        if "adapter_metadata" in data and isinstance(data["adapter_metadata"], str):
            data["adapter_metadata"] = json.loads(data["adapter_metadata"])
        return cls(**data)


@dataclass
class Recording:
    """Represents a terminal recording file."""

    recording_id: Optional[int]
    session_id: str
    file_path: str
    recording_type: str  # 'text' or 'video'
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert recording to dictionary."""
        data = asdict(self)
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recording":
        """Create recording from dictionary."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
