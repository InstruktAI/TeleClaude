"""Data models for TeleClaude sessions."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, cast

from teleclaude.constants import FIELD_ADAPTER_METADATA, FIELD_COMMAND, FIELD_COMPUTER
from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.feedback import get_last_feedback
from teleclaude.types import SystemStats

if TYPE_CHECKING:

    class InlineKeyboardMarkup(Protocol):
        """Telegram inline keyboard marker interface for type checking."""


# JSON-serializable types for database storage
JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonDict = dict[str, JsonValue]


def asdict_exclude_none(
    obj: "SessionAdapterMetadata | TelegramAdapterMetadata | RedisTransportMetadata | dict[str, JsonValue]",
) -> JsonDict:
    """Convert dataclass to dict, recursively excluding None values."""

    # Handle already-dict objects (defensive)
    def _exclude_none(data: object) -> JsonValue:
        """Recursively exclude None values from dicts and lists."""
        if isinstance(data, dict):
            result: dict[str, JsonValue] = {}
            for key, value in data.items():
                if value is None:
                    continue
                result[str(key)] = _exclude_none(value)
            return result
        if isinstance(data, list):
            return [_exclude_none(item) for item in data]
        return cast(JsonPrimitive, data)

    if isinstance(obj, dict):
        return cast(JsonDict, _exclude_none(obj))

    # asdict needs a dataclass instance
    result = cast(JsonDict, asdict(obj))
    return cast(JsonDict, _exclude_none(result))


@dataclass
class BaseCommandContext:
    """Base context - all session-based commands have session_id."""

    session_id: str


@dataclass
class SessionCommandContext(BaseCommandContext):
    """Context for simple session commands (list_sessions, get_session_data, etc.)."""

    args: List[str] = field(default_factory=list)


@dataclass
class NewSessionContext(BaseCommandContext):
    """Context for new_session/create_session commands."""

    args: List[str] = field(default_factory=list)
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
class PeerInfo:  # pylint: disable=too-many-instance-attributes
    """Information about a discovered peer computer."""

    name: str
    status: str  # "online" or "offline"
    last_seen: datetime
    adapter_type: str
    user: Optional[str] = None
    host: Optional[str] = None
    ip: Optional[str] = None
    role: Optional[str] = None
    system_stats: Optional[SystemStats] = None
    tmux_binary: Optional[str] = None


@dataclass
class TelegramAdapterMetadata:
    """Telegram-specific adapter metadata."""

    topic_id: Optional[int] = None
    output_message_id: Optional[str] = None
    footer_message_id: Optional[str] = None
    output_suppressed: bool = False
    parse_mode: Optional[str] = None
    char_offset: int = 0


@dataclass
class UiAdapterMetadata:
    """Metadata container for UI adapters."""

    _telegram: Optional[TelegramAdapterMetadata] = None

    def get_telegram(self) -> TelegramAdapterMetadata:
        """Get Telegram metadata, initializing if missing."""
        if self._telegram is None:
            self._telegram = TelegramAdapterMetadata()
        return self._telegram


@dataclass
class RedisTransportMetadata:  # pylint: disable=too-many-instance-attributes
    """Redis-specific adapter metadata."""

    channel_id: Optional[str] = None
    output_stream: Optional[str] = None
    target_computer: Optional[str] = None
    native_session_id: Optional[str] = None
    project_path: Optional[str] = None
    last_checkpoint_time: Optional[str] = None
    title: Optional[str] = None
    channel_metadata: Optional[str] = None  # JSON string


@dataclass
class SessionAdapterMetadata:
    """Typed metadata container for all adapters."""

    _ui: UiAdapterMetadata = field(default_factory=UiAdapterMetadata)
    redis: Optional[RedisTransportMetadata] = None

    def __init__(
        self,
        telegram: Optional[TelegramAdapterMetadata] = None,
        redis: Optional[RedisTransportMetadata] = None,
        _ui: Optional[UiAdapterMetadata] = None,
    ) -> None:
        """Initialize with backward compatibility for 'telegram' arg."""
        if _ui is not None:
            self._ui = _ui
        else:
            self._ui = UiAdapterMetadata(_telegram=telegram)
        self.redis = redis

    def get_ui(self) -> UiAdapterMetadata:
        """Get UI adapter metadata container."""
        return self._ui

    def to_json(self) -> str:
        """Serialize to JSON string, excluding None fields.

        Flattens UI adapters back to root keys for backward compatibility.
        """
        # manual dict construction to preserve "telegram" at root
        data: Dict[str, JsonValue] = {}

        # UI Adapters (flattened)
        if self._ui._telegram:
            data["telegram"] = asdict_exclude_none(self._ui._telegram)

        # Transport Adapters
        if self.redis:
            data["redis"] = asdict_exclude_none(self.redis)

        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "SessionAdapterMetadata":
        """Deserialize from JSON string, filtering unknown fields per adapter."""
        data_obj: object = json.loads(raw)
        telegram_metadata: Optional[TelegramAdapterMetadata] = None
        redis_metadata: Optional[RedisTransportMetadata] = None

        if isinstance(data_obj, dict):
            tg_raw = data_obj.get("telegram")
            if isinstance(tg_raw, dict):
                topic_id_val: object = tg_raw.get("topic_id")
                output_msg_val: object = tg_raw.get("output_message_id")
                footer_val: object = tg_raw.get("footer_message_id") or tg_raw.get("threaded_footer_message_id")
                topic_id: int | None = None
                if isinstance(topic_id_val, int):
                    topic_id = topic_id_val
                elif isinstance(topic_id_val, str) and topic_id_val.isdigit():
                    topic_id = int(topic_id_val)
                output_message_id = str(output_msg_val) if output_msg_val is not None else None
                footer_message_id = str(footer_val) if footer_val is not None else None
                output_suppressed = bool(tg_raw.get("output_suppressed", False))
                parse_mode = str(tg_raw.get("parse_mode")) if tg_raw.get("parse_mode") else None
                char_offset = int(tg_raw.get("char_offset", 0))
                telegram_metadata = TelegramAdapterMetadata(
                    topic_id=topic_id,
                    output_message_id=output_message_id,
                    footer_message_id=footer_message_id,
                    output_suppressed=output_suppressed,
                    parse_mode=parse_mode,
                    char_offset=char_offset,
                )

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

                redis_metadata = RedisTransportMetadata(
                    channel_id=_get_str("channel_id"),
                    output_stream=_get_str("output_stream"),
                    target_computer=_get_str("target_computer"),
                    native_session_id=_get_str("native_session_id"),
                    project_path=_get_str("project_path"),
                    last_checkpoint_time=_get_str("last_checkpoint_time"),
                    title=_get_str("title"),
                    channel_metadata=channel_meta_str,
                )

        # Reconstruct hierarchy
        ui_metadata = UiAdapterMetadata(_telegram=telegram_metadata)
        return cls(_ui=ui_metadata, redis=redis_metadata)


@dataclass
class ChannelMetadata:
    """Per-call metadata for create_channel operations."""

    target_computer: Optional[str] = None
    origin: bool = False


@dataclass
class MessageMetadata:
    """Per-call metadata for message operations."""

    reply_markup: Optional["InlineKeyboardMarkup"] = None
    parse_mode: str | None = "MarkdownV2"
    message_thread_id: Optional[int] = None
    raw_format: bool = False
    origin: Optional[str] = None
    channel_id: Optional[str] = None
    title: Optional[str] = None
    project_path: Optional[str] = None
    subdir: Optional[str] = None
    channel_metadata: Optional[Dict[str, object]] = None  # guard: loose-dict
    auto_command: Optional[str] = None  # legacy adapter boundary (deprecated)
    launch_intent: Optional["SessionLaunchIntent"] = None


@dataclass
class SessionLaunchIntent:
    """Normalized session launch intent (adapter boundary to core)."""

    kind: "SessionLaunchKind"
    agent: Optional[str] = None
    thinking_mode: Optional[str] = None
    message: Optional[str] = None
    native_session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind.value,
            "agent": self.agent,
            "thinking_mode": self.thinking_mode,
            "message": self.message,
            "native_session_id": self.native_session_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "SessionLaunchIntent":
        if FIELD_KIND not in data or data[FIELD_KIND] is None:
            raise ValueError("launch_intent.kind is required")
        return cls(
            kind=SessionLaunchKind(str(data[FIELD_KIND])),
            agent=cast(Optional[str], data.get("agent")),
            thinking_mode=cast(Optional[str], data.get("thinking_mode")),
            message=cast(Optional[str], data.get("message")),
            native_session_id=cast(Optional[str], data.get("native_session_id")),
        )


class SessionLaunchKind(Enum):
    EMPTY = "empty"
    AGENT = "agent"
    AGENT_THEN_MESSAGE = "agent_then_message"
    AGENT_RESUME = "agent_resume"


FIELD_KIND = "kind"


class CleanupTrigger(Enum):
    """When an ephemeral UI message should be removed."""

    NEXT_NOTICE = "next_notice"
    NEXT_TURN = "next_turn"


class SessionField(Enum):
    """Session field names used in updates/events."""

    ADAPTER_METADATA = "adapter_metadata"
    TITLE = "title"
    PROJECT_PATH = "project_path"
    SUBDIR = "subdir"
    LAST_MESSAGE_SENT = "last_message_sent"
    LAST_MESSAGE_SENT_AT = "last_message_sent_at"
    LAST_FEEDBACK_RECEIVED = "last_feedback_received"
    LAST_FEEDBACK_RECEIVED_AT = "last_feedback_received_at"
    LAST_TOOL_DONE_AT = "last_tool_done_at"
    LAST_TOOL_USE_AT = "last_tool_use_at"
    LAST_CHECKPOINT_AT = "last_checkpoint_at"


class TranscriptFormat(str, Enum):
    """Output format for session transcripts."""

    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class Session:  # pylint: disable=too-many-instance-attributes
    """Represents a tmux session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    title: str
    last_input_origin: Optional[str] = None
    adapter_metadata: SessionAdapterMetadata = field(default_factory=SessionAdapterMetadata)
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    project_path: Optional[str] = None
    subdir: Optional[str] = None
    description: Optional[str] = None
    initiated_by_ai: bool = False
    initiator_session_id: Optional[str] = None
    output_message_id: Optional[str] = None
    notification_sent: bool = False
    native_session_id: Optional[str] = None
    native_log_file: Optional[str] = None
    active_agent: Optional[str] = None
    thinking_mode: Optional[str] = None
    tui_log_file: Optional[str] = None
    tui_capture_started: bool = False
    last_message_sent: Optional[str] = None
    last_message_sent_at: Optional[datetime] = None
    last_feedback_received: Optional[str] = None
    last_feedback_received_at: Optional[datetime] = None
    last_feedback_summary: Optional[str] = None
    last_output_digest: Optional[str] = None
    last_tool_done_at: Optional[datetime] = None
    last_tool_use_at: Optional[datetime] = None
    last_checkpoint_at: Optional[datetime] = None
    working_slug: Optional[str] = None
    human_email: Optional[str] = None
    human_role: Optional[str] = None
    lifecycle_status: str = "active"

    def get_metadata(self) -> SessionAdapterMetadata:
        """Get session adapter metadata."""
        return self.adapter_metadata

    def to_dict(self) -> Dict[str, object]:  # guard: loose-dict - Serialization output
        """Convert session to dictionary for JSON serialization."""
        data = cast(Dict[str, object], asdict(self))
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        if self.last_message_sent_at:
            data["last_message_sent_at"] = self.last_message_sent_at.isoformat()
        if self.last_feedback_received_at:
            data["last_feedback_received_at"] = self.last_feedback_received_at.isoformat()
        if self.last_tool_done_at:
            data["last_tool_done_at"] = self.last_tool_done_at.isoformat()
        if self.last_tool_use_at:
            data["last_tool_use_at"] = self.last_tool_use_at.isoformat()
        if self.last_checkpoint_at:
            data["last_checkpoint_at"] = self.last_checkpoint_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        data["lifecycle_status"] = self.lifecycle_status
        adapter_meta = self.adapter_metadata
        if isinstance(adapter_meta, dict):
            data["adapter_metadata"] = json.dumps(adapter_meta)
        else:
            data["adapter_metadata"] = adapter_meta.to_json()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Session":  # guard: loose-dict - Deserialization input
        """Create session from dictionary (from database/JSON)."""

        created_at_raw = data.get("created_at")
        created_at = parse_iso_datetime(created_at_raw) if isinstance(created_at_raw, str) else created_at_raw

        last_activity_raw = data.get("last_activity")
        last_activity = (
            parse_iso_datetime(last_activity_raw) if isinstance(last_activity_raw, str) else last_activity_raw
        )

        closed_at_raw = data.get("closed_at")
        closed_at = parse_iso_datetime(closed_at_raw) if isinstance(closed_at_raw, str) else closed_at_raw

        last_message_sent_at_raw = data.get("last_message_sent_at")
        last_message_sent_at = (
            parse_iso_datetime(last_message_sent_at_raw)
            if isinstance(last_message_sent_at_raw, str)
            else last_message_sent_at_raw
        )

        last_feedback_received_at_raw = data.get("last_feedback_received_at")
        last_feedback_received_at = (
            parse_iso_datetime(last_feedback_received_at_raw)
            if isinstance(last_feedback_received_at_raw, str)
            else last_feedback_received_at_raw
        )
        last_tool_done_at_raw = data.get("last_tool_done_at")
        last_tool_done_at = (
            parse_iso_datetime(last_tool_done_at_raw)
            if isinstance(last_tool_done_at_raw, str)
            else last_tool_done_at_raw
        )
        last_tool_use_at_raw = data.get("last_tool_use_at")
        last_tool_use_at = (
            parse_iso_datetime(last_tool_use_at_raw) if isinstance(last_tool_use_at_raw, str) else last_tool_use_at_raw
        )
        last_checkpoint_at_raw = data.get("last_checkpoint_at")
        last_checkpoint_at = (
            parse_iso_datetime(last_checkpoint_at_raw)
            if isinstance(last_checkpoint_at_raw, str)
            else last_checkpoint_at_raw
        )

        adapter_metadata: SessionAdapterMetadata
        if FIELD_ADAPTER_METADATA in data and isinstance(data[FIELD_ADAPTER_METADATA], str):
            adapter_metadata = SessionAdapterMetadata.from_json(data[FIELD_ADAPTER_METADATA])
        else:
            adapter_metadata = SessionAdapterMetadata()

        ia_val = data.get("initiated_by_ai")
        initiated_by_ai = bool(ia_val) if ia_val is not None else False

        notification_sent_val = data.get("notification_sent")
        notification_sent = bool(notification_sent_val) if notification_sent_val is not None else False

        tui_capture_started_val = data.get("tui_capture_started")
        tui_capture_started = bool(tui_capture_started_val) if tui_capture_started_val is not None else False

        def _get_optional_str(key: str) -> Optional[str]:
            value = data.get(key)
            return str(value) if value is not None else None

        return cls(
            session_id=_get_optional_str("session_id") or "",
            computer_name=_get_optional_str("computer_name") or "",
            tmux_session_name=_get_optional_str("tmux_session_name") or "",
            title=_get_optional_str("title") or "",
            adapter_metadata=adapter_metadata,
            created_at=ensure_utc(created_at) if isinstance(created_at, datetime) else None,
            last_activity=ensure_utc(last_activity) if isinstance(last_activity, datetime) else None,
            closed_at=ensure_utc(closed_at) if isinstance(closed_at, datetime) else None,
            project_path=_get_optional_str("project_path"),
            subdir=_get_optional_str("subdir"),
            description=_get_optional_str("description"),
            initiated_by_ai=initiated_by_ai,
            initiator_session_id=_get_optional_str("initiator_session_id"),
            output_message_id=_get_optional_str("output_message_id"),
            last_input_origin=_get_optional_str("last_input_origin"),
            notification_sent=notification_sent,
            native_session_id=_get_optional_str("native_session_id"),
            native_log_file=_get_optional_str("native_log_file"),
            active_agent=_get_optional_str("active_agent"),
            thinking_mode=_get_optional_str("thinking_mode"),
            tui_log_file=_get_optional_str("tui_log_file"),
            tui_capture_started=tui_capture_started,
            last_message_sent=_get_optional_str("last_message_sent"),
            last_message_sent_at=ensure_utc(last_message_sent_at)
            if isinstance(last_message_sent_at, datetime)
            else None,
            last_feedback_received=_get_optional_str("last_feedback_received"),
            last_feedback_received_at=ensure_utc(last_feedback_received_at)
            if isinstance(last_feedback_received_at, datetime)
            else None,
            last_tool_done_at=ensure_utc(last_tool_done_at) if isinstance(last_tool_done_at, datetime) else None,
            last_tool_use_at=ensure_utc(last_tool_use_at) if isinstance(last_tool_use_at, datetime) else None,
            last_checkpoint_at=ensure_utc(last_checkpoint_at) if isinstance(last_checkpoint_at, datetime) else None,
            last_feedback_summary=_get_optional_str("last_feedback_summary"),
            last_output_digest=_get_optional_str("last_output_digest"),
            working_slug=_get_optional_str("working_slug"),
            human_email=_get_optional_str("human_email"),
            human_role=_get_optional_str("human_role"),
            lifecycle_status=str(data.get("lifecycle_status") or "active"),
        )


@dataclass
class Recording:
    """Represents a tmux recording file."""

    recording_id: Optional[int]
    session_id: str
    file_path: str
    recording_type: str
    timestamp: Optional[datetime] = None

    def to_dict(self) -> JsonDict:
        """Convert recording to dictionary."""
        data = cast(JsonDict, asdict(self))
        if self.timestamp:
            data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: JsonDict) -> "Recording":
        """Create recording from dictionary (from database/JSON)."""
        timestamp_raw = data.get("timestamp")
        if isinstance(timestamp_raw, str):
            timestamp = parse_iso_datetime(timestamp_raw)
        elif isinstance(timestamp_raw, datetime):
            timestamp = ensure_utc(timestamp_raw)
        else:
            timestamp = None
        return cls(
            recording_id=cast(Optional[int], data.get("recording_id")),
            session_id=str(data.get("session_id", "")),
            file_path=str(data.get("file_path", "")),
            recording_type=str(data.get("recording_type", "")),
            timestamp=timestamp,
        )


class ThinkingMode(str, Enum):
    """Model tier: fast/med/slow."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"
    DEEP = "deep"


@dataclass
class StartSessionArgs:
    """Typed arguments for starting a session via MCP/Redis tools."""

    computer: str
    project_path: str
    title: str
    message: str
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    caller_session_id: Optional[str] = None

    @classmethod
    def from_mcp(
        cls,
        arguments: Dict[str, object],  # guard: loose-dict - MCP protocol boundary
        caller_session_id: Optional[str],
    ) -> "StartSessionArgs":
        """Build args from MCP tool call."""
        required = ["computer", "project_path", "title", "message"]
        missing = [r for r in required if r not in arguments]
        if missing:
            raise ValueError(f"Arguments required for teleclaude__start_session: {', '.join(missing)}")

        agent = str(arguments.get("agent", "claude"))
        thinking_mode_raw = arguments.get("thinking_mode")
        if isinstance(thinking_mode_raw, ThinkingMode):
            thinking_mode_raw = thinking_mode_raw.value
        else:
            thinking_mode_raw = str(thinking_mode_raw or ThinkingMode.SLOW.value)

        allowed_modes = {mode.value for mode in ThinkingMode}
        if thinking_mode_raw not in allowed_modes:
            raise ValueError(f"thinking_mode must be one of: {', '.join(sorted(allowed_modes))}")
        thinking_mode = ThinkingMode(thinking_mode_raw)

        return cls(
            computer=str(arguments["computer"]),
            project_path=str(arguments["project_path"]),
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
    project: Optional[str] = None
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    subfolder: str = ""
    caller_session_id: Optional[str] = None

    @classmethod
    def from_mcp(
        cls,
        arguments: Dict[str, object],  # guard: loose-dict - MCP protocol boundary
        caller_session_id: Optional[str],
    ) -> "RunAgentCommandArgs":
        """Build args from MCP tool call."""
        if not arguments or FIELD_COMPUTER not in arguments or FIELD_COMMAND not in arguments:
            raise ValueError("Arguments required for teleclaude__run_agent_command: computer, command")

        thinking_mode_raw = arguments.get("thinking_mode")
        if isinstance(thinking_mode_raw, ThinkingMode):
            thinking_mode_raw = thinking_mode_raw.value
        else:
            thinking_mode_raw = str(thinking_mode_raw or ThinkingMode.SLOW.value)

        allowed_modes = {mode.value for mode in ThinkingMode}
        if thinking_mode_raw not in allowed_modes:
            raise ValueError(f"thinking_mode must be one of: {', '.join(sorted(allowed_modes))}")
        thinking_mode = ThinkingMode(thinking_mode_raw)

        project_arg = arguments.get("project")

        return cls(
            computer=str(arguments[FIELD_COMPUTER]),
            command=str(arguments[FIELD_COMMAND]),
            args=str(arguments.get("args", "")),
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
    channel_metadata: Optional[Dict[str, object]] = None  # guard: loose-dict
    initiator: Optional[str] = None
    project_path: Optional[str] = None
    title: Optional[str] = None
    origin: Optional[str] = None
    launch_intent: Optional[Dict[str, object]] = None  # guard: loose-dict
    reply_stream: Optional[str] = None


@dataclass
class SessionSummary:
    """Typed session summary for list_sessions output."""

    session_id: str
    last_input_origin: Optional[str]
    title: str
    thinking_mode: str | None
    active_agent: Optional[str]
    status: str
    project_path: Optional[str] = None
    subdir: Optional[str] = None
    created_at: Optional[str] = None
    last_activity: Optional[str] = None
    last_input: Optional[str] = None
    last_input_at: Optional[str] = None
    last_output_summary: Optional[str] = None
    last_output_summary_at: Optional[str] = None
    last_output_digest: Optional[str] = None
    native_session_id: Optional[str] = None
    tmux_session_name: Optional[str] = None
    initiator_session_id: Optional[str] = None
    computer: Optional[str] = None
    human_email: Optional[str] = None
    human_role: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:  # guard: loose-dict - Serialization output
        return {
            "session_id": self.session_id,
            "last_input_origin": self.last_input_origin,
            "title": self.title,
            "project_path": self.project_path,
            "subdir": self.subdir,
            "thinking_mode": self.thinking_mode,
            "active_agent": self.active_agent,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "last_input": self.last_input,
            "last_input_at": self.last_input_at,
            "last_output_summary": self.last_output_summary,
            "last_output_summary_at": self.last_output_summary_at,
            "last_output_digest": self.last_output_digest,
            "native_session_id": self.native_session_id,
            "tmux_session_name": self.tmux_session_name,
            "initiator_session_id": self.initiator_session_id,
            "computer": self.computer,
            "human_email": self.human_email,
            "human_role": self.human_role,
        }

    @classmethod
    def from_db_session(cls, session: "Session", computer: Optional[str] = None) -> "SessionSummary":
        """Create from database Session object."""
        return cls(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            thinking_mode=session.thinking_mode,
            active_agent=session.active_agent,
            status=session.lifecycle_status,
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            last_input=session.last_message_sent,
            last_input_at=session.last_message_sent_at.isoformat() if session.last_message_sent_at else None,
            last_output_summary=get_last_feedback(session),
            last_output_summary_at=(
                session.last_feedback_received_at.isoformat() if session.last_feedback_received_at else None
            ),
            last_output_digest=session.last_output_digest,
            native_session_id=session.native_session_id,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
            computer=computer,
            human_email=session.human_email,
            human_role=session.human_role,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "SessionSummary":  # guard: loose-dict
        """Create from dict."""
        return cls(
            session_id=str(data["session_id"]),
            last_input_origin=str(data.get("last_input_origin")) if data.get("last_input_origin") else None,
            title=str(data["title"]),
            project_path=str(data.get("project_path")) if data.get("project_path") else None,
            subdir=str(data.get("subdir")) if data.get("subdir") else None,
            thinking_mode=str(data["thinking_mode"]) if data.get("thinking_mode") is not None else None,
            active_agent=str(data.get("active_agent")) if data.get("active_agent") else None,
            status=str(data["status"]),
            created_at=str(data.get("created_at")) if data.get("created_at") else None,
            last_activity=str(data.get("last_activity")) if data.get("last_activity") else None,
            last_input=str(data.get("last_input")) if data.get("last_input") else None,
            last_input_at=str(data.get("last_input_at")) if data.get("last_input_at") else None,
            last_output_summary=(
                str(data.get("last_output_summary") or data.get("last_output"))
                if (data.get("last_output_summary") or data.get("last_output"))
                else None
            ),
            last_output_summary_at=(
                str(data.get("last_output_summary_at") or data.get("last_output_at"))
                if (data.get("last_output_summary_at") or data.get("last_output_at"))
                else None
            ),
            last_output_digest=str(data.get("last_output_digest")) if data.get("last_output_digest") else None,
            native_session_id=str(data.get("native_session_id")) if data.get("native_session_id") else None,
            tmux_session_name=str(data.get("tmux_session_name")) if data.get("tmux_session_name") else None,
            initiator_session_id=str(data.get("initiator_session_id")) if data.get("initiator_session_id") else None,
            computer=str(data.get("computer")) if data.get("computer") else None,
            human_email=str(data.get("human_email")) if data.get("human_email") else None,
            human_role=str(data.get("human_role")) if data.get("human_role") else None,
        )


@dataclass
class AgentStartArgs:
    """Typed arguments for agent start."""

    agent_name: str
    thinking_mode: ThinkingMode
    user_args: List[str]


@dataclass
class AgentResumeArgs:
    """Typed arguments for agent resume."""

    agent_name: str
    native_session_id: Optional[str]
    thinking_mode: Optional[ThinkingMode]


@dataclass
class KillArgs:
    """Typed arguments for kill command."""

    pass


@dataclass
class SystemCommandArgs:
    """Typed arguments for system commands."""

    command: str


@dataclass
class MessagePayload:
    """Payload for MESSAGE events."""

    session_id: str
    text: str
    project_path: Optional[str] = None
    title: Optional[str] = None


@dataclass
class ComputerInfo:
    """Information about a computer (local or remote)."""

    name: str
    status: str
    user: Optional[str] = None
    host: Optional[str] = None
    role: Optional[str] = None
    is_local: bool = False
    system_stats: Optional[SystemStats] = None
    tmux_binary: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:  # guard: loose-dict
        return cast(Dict[str, object], asdict(self))


@dataclass
class TodoInfo:
    """Information about a work item todo."""

    slug: str
    status: str
    description: Optional[str] = None
    has_requirements: bool = False
    has_impl_plan: bool = False
    build_status: Optional[str] = None
    review_status: Optional[str] = None
    dor_status: Optional[str] = None
    dor_score: Optional[int] = None
    deferrals_status: Optional[str] = None
    findings_count: int = 0
    files: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "TodoInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        dor_score_raw = data.get("dor_score")
        dor_score: Optional[int]
        try:
            dor_score = int(dor_score_raw) if dor_score_raw is not None else None
        except (TypeError, ValueError):
            dor_score = None

        return cls(
            slug=str(data.get("slug", "")),
            status=str(data.get("status", "pending")),
            description=str(data.get("description") or data.get("title") or ""),
            has_requirements=bool(data.get("has_requirements", False)),
            has_impl_plan=bool(data.get("has_impl_plan", False)),
            build_status=cast(Optional[str], data.get("build_status")),
            review_status=cast(Optional[str], data.get("review_status")),
            dor_status=cast(Optional[str], data.get("dor_status")),
            dor_score=dor_score,
            deferrals_status=cast(Optional[str], data.get("deferrals_status")),
            findings_count=int(data.get("findings_count", 0) or 0),
            files=[str(f) for f in cast(List[object], data.get("files", []))],
        )

    def to_dict(self) -> Dict[str, object]:  # guard: loose-dict
        """Convert to dict."""
        return cast(Dict[str, object], asdict(self))


@dataclass
class ProjectInfo:
    """Information about a project directory."""

    name: str
    path: str
    description: Optional[str] = None
    computer: Optional[str] = None
    todos: List[TodoInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ProjectInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        # fmt: off
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            description=str(data.get("description") or data.get("desc") or ""),
            computer=cast(Optional[str], data.get("computer")),
            todos=[TodoInfo.from_dict(t) for t in cast(List[Dict[str, object]], data.get("todos", []))],  # guard: loose-dict
        )
        # fmt: on

    def to_dict(self) -> Dict[str, object]:  # guard: loose-dict
        """Convert to dict."""
        result = cast(Dict[str, object], asdict(self))
        result["todos"] = [t.to_dict() for t in self.todos]
        return result


@dataclass
class CommandPayload:
    """Generic command payload with args."""

    session_id: str
    args: List[str]
    project_path: Optional[str] = None
    title: Optional[str] = None
