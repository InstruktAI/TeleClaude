"""Data models for TeleClaude sessions."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from telegram.types import InlineKeyboardMarkup  # type: ignore[import-not-found]

# JSON-serializable types for database storage
JsonPrimitive = Union[str, int, float, bool, None]
JsonValue = Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]]
JsonDict = dict[str, JsonValue]


def asdict_exclude_none(obj: object) -> dict[str, object]:
    """Convert dataclass to dict, recursively excluding None values.

    Replacement for Pydantic's model_dump(exclude_none=True).
    Handles nested dataclasses by recursively excluding None.
    """
    # Handle already-dict objects (defensive)
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if v is not None}

    result: dict[str, object] = asdict(obj)  # type: ignore[call-overload]  # asdict accepts dataclass instances

    def _exclude_none(data: object) -> object:
        """Recursively exclude None values from dicts."""
        if isinstance(data, dict):
            return {k: _exclude_none(v) for k, v in data.items() if v is not None}  # type: ignore[misc]
        if isinstance(data, list):
            return [_exclude_none(item) for item in data]
        return data

    return _exclude_none(result)  # type: ignore[return-value]  # _exclude_none returns dict for dict input


@dataclass
class BaseCommandContext:
    """Base context - all session-based commands have session_id."""

    session_id: str


@dataclass
class SessionCommandContext(BaseCommandContext):
    """Context for simple session commands (list_sessions, get_session_data, etc.)."""

    args: list[str] = field(default_factory=list)


@dataclass
class NewSessionContext(BaseCommandContext):
    """Context for new_session/create_session commands."""

    args: list[str] = field(default_factory=list)
    title: Optional[str] = None


@dataclass
class MessageContext(BaseCommandContext):
    """Context for message events."""

    text: str = ""


@dataclass
class VoiceContext(BaseCommandContext):
    """Context for voice message events."""

    file_path: str = ""


@dataclass
class FileContext(BaseCommandContext):
    """Context for file upload events."""

    file_path: str = ""
    filename: str = ""


@dataclass
class SystemCommandContext:
    """Context for system commands (no session_id)."""

    command: str = ""
    from_computer: str = "unknown"


class AdapterType(str, Enum):
    """Adapter type enum."""

    TELEGRAM = "telegram"
    REDIS = "redis"


@dataclass
class PeerInfo:  # pylint: disable=too-many-instance-attributes  # Data model for peer discovery info
    """Information about a discovered peer computer."""

    name: str
    status: str  # "online" or "offline"
    last_seen: datetime
    adapter_type: str  # Which adapter discovered this peer
    user: Optional[str] = None
    host: Optional[str] = None
    ip: Optional[str] = None
    role: Optional[str] = None
    system_stats: Optional[dict[str, object]] = None  # memory, disk, cpu stats


@dataclass
class TelegramAdapterMetadata:
    """Telegram-specific adapter metadata."""

    topic_id: Optional[int] = None
    output_message_id: Optional[str] = None


@dataclass
class RedisAdapterMetadata:  # pylint: disable=too-many-instance-attributes  # Data model for Redis adapter metadata
    """Redis-specific adapter metadata."""

    channel_id: Optional[str] = None  # Stream key
    output_stream: Optional[str] = None

    # MCP/AI-to-AI session fields
    target_computer: Optional[str] = None
    native_session_id: Optional[str] = None
    project_dir: Optional[str] = None
    last_checkpoint_time: Optional[str] = None
    title: Optional[str] = None
    channel_metadata: Optional[str] = None  # JSON string


@dataclass
class SessionAdapterMetadata:
    """Typed metadata container for all adapters."""

    telegram: Optional[TelegramAdapterMetadata] = None
    redis: Optional[RedisAdapterMetadata] = None


@dataclass
class ChannelMetadata:
    """Per-call metadata for create_channel operations.

    Contains options that affect HOW a channel is created.
    """

    target_computer: Optional[str] = None
    origin: bool = False


@dataclass  # type: ignore[misc]
class MessageMetadata:  # type: ignore[no-any-unimported]  # pylint: disable=too-many-instance-attributes  # Metadata container for message operations
    """Per-call metadata for send_message/edit_message operations (transient call-level data).

    This dataclass contains options that affect HOW a single message is sent,
    not persistent session state. Different adapters use different fields:

    - Telegram: reply_markup, parse_mode, message_thread_id
    - All UI adapters: raw_format
    - Redis: adapter_type
    """

    # Telegram-specific formatting
    reply_markup: Optional["InlineKeyboardMarkup"] = None  # type: ignore[no-any-unimported]
    parse_mode: str = "Markdown"
    message_thread_id: Optional[int] = None

    # Shared formatting options
    raw_format: bool = False

    # Adapter identification
    adapter_type: Optional[str] = None

    # Generic pass-through (for event routing)
    channel_id: Optional[str] = None

    # Session creation fields (for send_request with new_session command)
    title: Optional[str] = None
    project_dir: Optional[str] = None
    channel_metadata: Optional[dict[str, object]] = None

    # Auto-command to run after session creation (e.g., "claude", "claude_resume")
    auto_command: Optional[str] = None


@dataclass
class Session:  # pylint: disable=too-many-instance-attributes  # Data model for terminal sessions
    """Represents a terminal session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    origin_adapter: str  # Single origin adapter (e.g., "redis" or "telegram")
    title: str
    adapter_metadata: SessionAdapterMetadata = field(default_factory=SessionAdapterMetadata)
    closed: bool = False
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    terminal_size: str = "80x24"
    working_directory: str = "~"
    description: Optional[str] = None
    ux_state: Optional[str] = None  # JSON blob for session-level UX state
    initiated_by_ai: bool = False  # True if session was created via AI-to-AI (uses Sonnet model)

    def to_dict(self) -> JsonDict:
        """Convert session to dictionary for JSON serialization."""
        data: JsonDict = asdict(self)  # asdict returns dict[str, Any]
        # Convert datetime to ISO format
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        # Convert SessionAdapterMetadata (dataclass) to JSON string for DB storage
        data["adapter_metadata"] = json.dumps(asdict_exclude_none(self.adapter_metadata))
        return data

    @classmethod
    def from_dict(cls, data: JsonDict) -> "Session":
        """Create session from dictionary (from database/JSON)."""
        # Parse datetime strings
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])  # type: ignore[assignment]
        if "last_activity" in data and isinstance(data["last_activity"], str):
            data["last_activity"] = datetime.fromisoformat(data["last_activity"])  # type: ignore[assignment]

        # Parse adapter_metadata JSON to SessionAdapterMetadata
        if "adapter_metadata" in data and isinstance(data["adapter_metadata"], str):
            raw_metadata: dict[str, object] = json.loads(data["adapter_metadata"])
            # Build SessionAdapterMetadata from dict with typed adapter metadata
            telegram_metadata: Optional[TelegramAdapterMetadata] = None
            redis_metadata: Optional[RedisAdapterMetadata] = None

            for adapter_key, adapter_data in raw_metadata.items():
                if adapter_data is None or not isinstance(adapter_data, dict):
                    continue  # Skip None metadata or non-dict values
                if adapter_key == "telegram":
                    # Filter to only known fields (handles schema evolution)
                    known_fields = {"topic_id", "output_message_id"}
                    filtered = {k: v for k, v in adapter_data.items() if k in known_fields}  # type: ignore[misc]
                    telegram_metadata = TelegramAdapterMetadata(**filtered)  # type: ignore[misc]
                elif adapter_key == "redis":
                    # Filter to only known fields (handles schema evolution)
                    known_fields = {
                        "channel_id",
                        "output_stream",
                        "target_computer",
                        "native_session_id",
                        "project_dir",
                        "last_checkpoint_time",
                        "title",
                        "channel_metadata",
                    }
                    filtered = {k: v for k, v in adapter_data.items() if k in known_fields}
                    redis_metadata = RedisAdapterMetadata(**filtered)  # type: ignore[misc]

            data["adapter_metadata"] = SessionAdapterMetadata(telegram=telegram_metadata, redis=redis_metadata)  # type: ignore
        elif "adapter_metadata" not in data:
            # Ensure adapter_metadata always exists
            data["adapter_metadata"] = SessionAdapterMetadata()  # type: ignore

        # Convert closed from SQLite integer (0/1) to Python bool
        if "closed" in data and isinstance(data["closed"], int):
            data["closed"] = bool(data["closed"])

        # Convert initiated_by_ai from SQLite integer (0/1) to Python bool
        if "initiated_by_ai" in data and isinstance(data["initiated_by_ai"], int):
            data["initiated_by_ai"] = bool(data["initiated_by_ai"])

        # Filter to only Session's known fields (handles schema evolution/deprecated columns)
        known_fields = {
            "session_id",
            "computer_name",
            "tmux_session_name",
            "origin_adapter",
            "title",
            "adapter_metadata",
            "closed",
            "created_at",
            "last_activity",
            "terminal_size",
            "working_directory",
            "description",
            "ux_state",
            "initiated_by_ai",
        }
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        return cls(**filtered_data)  # type: ignore[arg-type]  # DB deserialization


@dataclass
class Recording:
    """Represents a terminal recording file."""

    recording_id: Optional[int]
    session_id: str
    file_path: str
    recording_type: str  # 'text' or 'video'
    timestamp: Optional[datetime] = None

    def to_dict(self) -> JsonDict:
        """Convert recording to dictionary."""
        data: JsonDict = asdict(self)  # asdict returns dict[str, Any]
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: JsonDict) -> "Recording":
        """Create recording from dictionary (from database/JSON)."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])  # type: ignore[assignment]
        return cls(**data)  # type: ignore[arg-type]  # DB deserialization
