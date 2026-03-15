"""Session model and related types for TeleClaude."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional, cast

from teleclaude.constants import FIELD_ADAPTER_METADATA, HUMAN_ROLE_ADMIN
from teleclaude.core.dates import ensure_utc, parse_iso_datetime

from ._adapter import SessionAdapterMetadata
from ._types import JsonDict

if TYPE_CHECKING:
    from ._context import InlineKeyboardMarkup


@dataclass
class ChannelMetadata:
    """Per-call metadata for create_channel operations."""

    target_computer: str | None = None


@dataclass(frozen=True)
class SessionMetadata:
    """Typed metadata for session identity and role."""

    system_role: str | None = None  # ROLE_* constant
    job: str | None = None  # JobRole value
    human_email: str | None = None
    human_role: str | None = None
    principal: str | None = None


@dataclass
class MessageMetadata:
    """Per-call metadata for message operations."""

    reply_markup: Optional["InlineKeyboardMarkup"] = None
    parse_mode: str | None = None
    message_thread_id: int | None = None
    raw_format: bool = False
    origin: str | None = None
    channel_id: str | None = None
    title: str | None = None
    project_path: str | None = None
    subdir: str | None = None
    channel_metadata: dict[str, object] | None = None  # guard: loose-dict
    session_metadata: "SessionMetadata | None" = None
    auto_command: str | None = None  # legacy adapter boundary (deprecated)
    launch_intent: Optional["SessionLaunchIntent"] = None
    is_transcription: bool = False
    cleanup_trigger: str | None = None
    reflection_actor_id: str | None = None
    reflection_actor_name: str | None = None
    reflection_actor_avatar_url: str | None = None
    reflection_origin: str | None = None


@dataclass
class SessionLaunchIntent:
    """Normalized session launch intent (adapter boundary to core)."""

    kind: "SessionLaunchKind"
    agent: str | None = None
    thinking_mode: str | None = None
    message: str | None = None
    native_session_id: str | None = None

    def to_dict(self) -> JsonDict:
        return {
            "kind": self.kind.value,
            "agent": self.agent,
            "thinking_mode": self.thinking_mode,
            "message": self.message,
            "native_session_id": self.native_session_id,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> "SessionLaunchIntent":
        if FIELD_KIND not in data or data[FIELD_KIND] is None:
            raise ValueError("launch_intent.kind is required")
        return cls(
            kind=SessionLaunchKind(str(data[FIELD_KIND])),
            agent=cast(str | None, data.get("agent")),
            thinking_mode=cast(str | None, data.get("thinking_mode")),
            message=cast(str | None, data.get("message")),
            native_session_id=cast(str | None, data.get("native_session_id")),
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
    LAST_OUTPUT_RAW = "last_output_raw"
    LAST_OUTPUT_AT = "last_output_at"
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
    last_input_origin: str | None = None
    adapter_metadata: SessionAdapterMetadata = field(default_factory=SessionAdapterMetadata)
    session_metadata: SessionMetadata | None = None
    created_at: datetime | None = None
    last_activity: datetime | None = None
    closed_at: datetime | None = None
    project_path: str | None = None
    subdir: str | None = None
    description: str | None = None
    initiated_by_ai: bool = False
    initiator_session_id: str | None = None
    output_message_id: str | None = None
    notification_sent: bool = False
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    tui_log_file: str | None = None
    tui_capture_started: bool = False
    last_message_sent: str | None = None
    last_message_sent_at: datetime | None = None
    last_output_raw: str | None = None
    last_output_at: datetime | None = None
    last_output_summary: str | None = None
    last_output_digest: str | None = None
    last_tool_done_at: datetime | None = None
    last_tool_use_at: datetime | None = None
    last_checkpoint_at: datetime | None = None
    turn_triggered_by_linked_output: bool = False
    working_slug: str | None = None
    human_email: str | None = None
    human_role: str | None = HUMAN_ROLE_ADMIN
    principal: str | None = None
    lifecycle_status: str = "active"
    last_memory_extraction_at: datetime | None = None
    help_desk_processed_at: datetime | None = None
    relay_status: str | None = None
    relay_discord_channel_id: str | None = None
    relay_started_at: datetime | None = None
    transcript_files: str = "[]"
    char_offset: int = 0
    visibility: str | None = "private"

    def get_metadata(self) -> SessionAdapterMetadata:
        """Get session adapter metadata."""
        return self.adapter_metadata

    def to_dict(self) -> JsonDict:
        """Convert session to dictionary for JSON serialization."""
        data = cast(JsonDict, asdict(self))
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        if self.last_message_sent_at:
            data["last_message_sent_at"] = self.last_message_sent_at.isoformat()
        if self.last_output_at:
            data["last_output_at"] = self.last_output_at.isoformat()
        if self.last_tool_done_at:
            data["last_tool_done_at"] = self.last_tool_done_at.isoformat()
        if self.last_tool_use_at:
            data["last_tool_use_at"] = self.last_tool_use_at.isoformat()
        if self.last_checkpoint_at:
            data["last_checkpoint_at"] = self.last_checkpoint_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        if self.last_memory_extraction_at:
            data["last_memory_extraction_at"] = self.last_memory_extraction_at.isoformat()
        if self.help_desk_processed_at:
            data["help_desk_processed_at"] = self.help_desk_processed_at.isoformat()
        if self.relay_started_at:
            data["relay_started_at"] = self.relay_started_at.isoformat()
        data["lifecycle_status"] = self.lifecycle_status
        adapter_meta = self.adapter_metadata
        if isinstance(adapter_meta, dict):
            data["adapter_metadata"] = json.dumps(adapter_meta)
        else:
            data["adapter_metadata"] = adapter_meta.to_json()
        if self.session_metadata:
            data["session_metadata"] = asdict(self.session_metadata)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Session":  # guard: loose-dict - Deserialization input
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

        last_output_at_raw = data.get("last_output_at")
        last_output_at = (
            parse_iso_datetime(last_output_at_raw) if isinstance(last_output_at_raw, str) else last_output_at_raw
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

        session_metadata_raw = data.get("session_metadata")
        session_metadata: SessionMetadata | None = None
        _sm_fields = {"system_role", "job", "human_email", "human_role", "principal"}
        if isinstance(session_metadata_raw, dict):
            session_metadata = SessionMetadata(**{k: v for k, v in session_metadata_raw.items() if k in _sm_fields})
        elif isinstance(session_metadata_raw, str):
            try:
                _raw = json.loads(session_metadata_raw)
                if isinstance(_raw, dict):
                    session_metadata = SessionMetadata(**{k: v for k, v in _raw.items() if k in _sm_fields})
            except json.JSONDecodeError:
                pass

        ia_val = data.get("initiated_by_ai")
        initiated_by_ai = bool(ia_val) if ia_val is not None else False

        notification_sent_val = data.get("notification_sent")
        notification_sent = bool(notification_sent_val) if notification_sent_val is not None else False

        tui_capture_started_val = data.get("tui_capture_started")
        tui_capture_started = bool(tui_capture_started_val) if tui_capture_started_val is not None else False

        def _get_optional_str(key: str) -> str | None:
            value = data.get(key)
            return str(value) if value is not None else None

        return cls(
            session_id=_get_optional_str("session_id") or "",
            computer_name=_get_optional_str("computer_name") or "",
            tmux_session_name=_get_optional_str("tmux_session_name") or "",
            title=_get_optional_str("title") or "",
            adapter_metadata=adapter_metadata,
            session_metadata=session_metadata,
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
            last_output_raw=_get_optional_str("last_output_raw"),
            last_output_at=ensure_utc(last_output_at) if isinstance(last_output_at, datetime) else None,
            last_tool_done_at=ensure_utc(last_tool_done_at) if isinstance(last_tool_done_at, datetime) else None,
            last_tool_use_at=ensure_utc(last_tool_use_at) if isinstance(last_tool_use_at, datetime) else None,
            last_checkpoint_at=ensure_utc(last_checkpoint_at) if isinstance(last_checkpoint_at, datetime) else None,
            last_output_summary=_get_optional_str("last_output_summary"),
            last_output_digest=_get_optional_str("last_output_digest"),
            working_slug=_get_optional_str("working_slug"),
            human_email=_get_optional_str("human_email"),
            human_role=_get_optional_str("human_role") or HUMAN_ROLE_ADMIN,
            lifecycle_status=str(data.get("lifecycle_status") or "active"),
            last_memory_extraction_at=parse_iso_datetime(data.get("last_memory_extraction_at"))
            if isinstance(data.get("last_memory_extraction_at"), str)
            else None,
            help_desk_processed_at=parse_iso_datetime(data.get("help_desk_processed_at"))
            if isinstance(data.get("help_desk_processed_at"), str)
            else None,
            relay_status=_get_optional_str("relay_status"),
            relay_discord_channel_id=_get_optional_str("relay_discord_channel_id"),
            relay_started_at=parse_iso_datetime(data.get("relay_started_at"))
            if isinstance(data.get("relay_started_at"), str)
            else None,
        )


@dataclass
class Recording:
    """Represents a tmux recording file."""

    recording_id: int | None
    session_id: str
    file_path: str
    recording_type: str
    timestamp: datetime | None = None

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
            recording_id=cast(int | None, data.get("recording_id")),
            session_id=str(data.get("session_id", "")),
            file_path=str(data.get("file_path", "")),
            recording_type=str(data.get("recording_type", "")),
            timestamp=timestamp,
        )
