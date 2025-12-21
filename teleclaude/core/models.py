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

    def to_json(self) -> str:
        """Serialize to JSON string, excluding None fields."""
        return json.dumps(asdict_exclude_none(self))

    @classmethod
    def from_json(cls, raw: str) -> "SessionAdapterMetadata":
        """Deserialize from JSON string, filtering unknown fields per adapter."""
        data_obj: object = json.loads(raw)
        telegram_metadata: Optional[TelegramAdapterMetadata] = None
        redis_metadata: Optional[RedisAdapterMetadata] = None

        if isinstance(data_obj, dict):
            tg_raw = data_obj.get("telegram")
            if isinstance(tg_raw, dict):
                topic_id_val: object = tg_raw.get("topic_id")
                output_msg_val: object = tg_raw.get("output_message_id")
                tg_fields: dict[str, object | None] = {
                    "topic_id": int(topic_id_val) if isinstance(topic_id_val, int) else None,
                    "output_message_id": str(output_msg_val) if output_msg_val is not None else None,
                }
                telegram_metadata = TelegramAdapterMetadata(**tg_fields)  # type: ignore[arg-type]

            redis_raw = data_obj.get("redis")
            if isinstance(redis_raw, dict):

                def _get_str(key: str) -> Optional[str]:
                    val = redis_raw.get(key)
                    return str(val) if val is not None else None

                channel_meta_val = redis_raw.get("channel_metadata")
                channel_meta_str: Optional[str]
                if isinstance(channel_meta_val, dict):
                    channel_meta_str = json.dumps(channel_meta_val)
                elif channel_meta_val is not None:
                    channel_meta_str = str(channel_meta_val)
                else:
                    channel_meta_str = None

                redis_metadata = RedisAdapterMetadata(
                    channel_id=_get_str("channel_id"),
                    output_stream=_get_str("output_stream"),
                    target_computer=_get_str("target_computer"),
                    native_session_id=_get_str("native_session_id"),
                    project_dir=_get_str("project_dir"),
                    last_checkpoint_time=_get_str("last_checkpoint_time"),
                    title=_get_str("title"),
                    channel_metadata=channel_meta_str,
                )

        return cls(telegram=telegram_metadata, redis=redis_metadata)


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
    parse_mode: str = ""
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
    terminal_size: str = "160x80"
    working_directory: str = "~"
    description: Optional[str] = None
    ux_state: Optional[str] = None  # JSON blob for session-level UX state
    initiated_by_ai: bool = False  # True if session was created via AI-to-AI

    def to_dict(self) -> dict[str, object]:
        """Convert session to dictionary for JSON serialization."""
        data: dict[str, object] = asdict(self)  # asdict returns dict[str, Any]
        # Convert datetime to ISO format
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        # Convert SessionAdapterMetadata (dataclass) to JSON string for DB storage
        adapter_meta = self.adapter_metadata
        if isinstance(adapter_meta, dict):
            data["adapter_metadata"] = json.dumps(adapter_meta)
        else:
            data["adapter_metadata"] = adapter_meta.to_json()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Session":
        """Create session from dictionary (from database/JSON)."""
        created_at_raw = data.get("created_at")
        created_at = datetime.fromisoformat(created_at_raw) if isinstance(created_at_raw, str) else created_at_raw

        last_activity_raw = data.get("last_activity")
        last_activity = (
            datetime.fromisoformat(last_activity_raw) if isinstance(last_activity_raw, str) else last_activity_raw
        )

        # Parse adapter_metadata JSON to SessionAdapterMetadata
        adapter_metadata: SessionAdapterMetadata
        if "adapter_metadata" in data and isinstance(data["adapter_metadata"], str):
            adapter_metadata = SessionAdapterMetadata.from_json(data["adapter_metadata"])
        else:
            adapter_metadata = SessionAdapterMetadata()

        # Convert closed from SQLite integer (0/1) to Python bool
        closed_val = data.get("closed")
        closed = bool(closed_val) if isinstance(closed_val, int) else closed_val

        # Convert initiated_by_ai from SQLite integer (0/1) to Python bool
        ia_val = data.get("initiated_by_ai")
        initiated_by_ai = bool(ia_val) if isinstance(ia_val, int) else ia_val

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
        filtered_data["adapter_metadata"] = adapter_metadata
        filtered_data["created_at"] = created_at
        filtered_data["last_activity"] = last_activity
        filtered_data["closed"] = closed
        filtered_data["initiated_by_ai"] = initiated_by_ai

        return cls(**filtered_data)  # type: ignore[arg-type]


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


# ==================== Helper models / validators ====================


class ThinkingMode(str, Enum):
    """Model tier: fast/med/slow (deep is codex-only for Telegram)."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"
    DEEP = "deep"


@dataclass
class StartSessionArgs:
    """Typed arguments for starting a session via MCP/Redis tools."""

    computer: str
    project_dir: str
    title: str
    message: str
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    caller_session_id: Optional[str] = None

    @classmethod
    def from_mcp(cls, arguments: dict[str, object], caller_session_id: Optional[str]) -> "StartSessionArgs":
        """Build args from MCP tool call."""
        required = ["computer", "project_dir", "title", "message"]
        missing = [r for r in required if r not in arguments]
        if missing:
            raise ValueError(f"Arguments required for teleclaude__start_session: {', '.join(missing)}")

        agent = str(arguments.get("agent", "claude"))
        thinking_mode_raw = str(arguments.get("thinking_mode", ThinkingMode.SLOW))
        allowed_modes = {ThinkingMode.FAST.value, ThinkingMode.MED.value, ThinkingMode.SLOW.value}
        if thinking_mode_raw not in allowed_modes:
            raise ValueError("thinking_mode must be one of: fast, med, slow")
        thinking_mode = ThinkingMode(thinking_mode_raw)

        return cls(
            computer=str(arguments["computer"]),
            project_dir=str(arguments["project_dir"]),
            title=str(arguments["title"]),
            message=str(arguments["message"]),
            agent=agent,
            thinking_mode=thinking_mode,
            caller_session_id=caller_session_id,
        )


@dataclass
class RunAgentCommandArgs:
    """Typed arguments for teleclaude__run_agent_command."""

    computer: str
    command: str
    args: str = ""
    session_id: Optional[str] = None
    project: Optional[str] = None
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    subfolder: str = ""
    caller_session_id: Optional[str] = None

    @classmethod
    def from_mcp(cls, arguments: dict[str, object], caller_session_id: Optional[str]) -> "RunAgentCommandArgs":
        """Build args from MCP tool call."""
        if not arguments or "computer" not in arguments or "command" not in arguments:
            raise ValueError("Arguments required for teleclaude__run_agent_command: computer, command")

        thinking_mode_raw = str(arguments.get("thinking_mode", ThinkingMode.SLOW))
        allowed_modes = {ThinkingMode.FAST.value, ThinkingMode.MED.value, ThinkingMode.SLOW.value}
        if thinking_mode_raw not in allowed_modes:
            raise ValueError("thinking_mode must be one of: fast, med, slow")
        thinking_mode = ThinkingMode(thinking_mode_raw)

        session_id_arg = arguments.get("session_id")
        project_arg = arguments.get("project")

        return cls(
            computer=str(arguments["computer"]),
            command=str(arguments["command"]),
            args=str(arguments.get("args", "")),
            session_id=str(session_id_arg) if session_id_arg else None,
            project=str(project_arg) if project_arg else None,
            agent=str(arguments.get("agent", "claude")),
            thinking_mode=thinking_mode,
            subfolder=str(arguments.get("subfolder", "")) if arguments.get("subfolder") else "",
            caller_session_id=caller_session_id,
        )


@dataclass
class RedisInboundMessage:
    """Typed Redis message parsed from raw stream entry."""

    msg_type: str
    session_id: Optional[str]
    command: str
    channel_metadata: Optional[dict[str, object]] = None
    initiator: Optional[str] = None
    project_dir: Optional[str] = None
    title: Optional[str] = None


@dataclass
class SessionSummary:
    """Typed session summary for list_sessions output."""

    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    thinking_mode: str
    status: str
    created_at: Optional[str]
    last_activity: Optional[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "origin_adapter": self.origin_adapter,
            "title": self.title,
            "working_directory": self.working_directory,
            "thinking_mode": self.thinking_mode,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
        }


@dataclass
class AgentStartArgs:
    """Typed arguments for agent start."""

    agent_name: str
    thinking_mode: ThinkingMode
    user_args: list[str]


@dataclass
class AgentResumeArgs:
    """Typed arguments for agent resume."""

    agent_name: str
    native_session_id: Optional[str]
    thinking_mode: ThinkingMode


@dataclass
class CdArgs:
    """Typed arguments for cd command."""

    path: Optional[str] = None  # None means list trusted dirs


@dataclass
class KillArgs:
    """Typed arguments for kill command (no fields yet, placeholder)."""

    pass


@dataclass
class SystemCommandArgs:
    """Typed arguments for system commands."""

    command: str


# Event payloads


@dataclass
class MessagePayload:
    """Payload for MESSAGE events."""

    session_id: str
    text: str
    project_dir: Optional[str] = None
    title: Optional[str] = None


@dataclass
class CommandPayload:
    """Generic command payload with args."""

    session_id: str
    args: list[str]
    project_dir: Optional[str] = None
    title: Optional[str] = None
