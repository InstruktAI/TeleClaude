"""Session model and related types for TeleClaude."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Optional, cast

from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.injected_text import TranscriptEntryKind
from teleclaude.session_fields import SessionRecentOutputFields, SessionRecentToolFields

from ._types import JsonDict, SessionOriginMetadata

if TYPE_CHECKING:
    from ._context import InlineKeyboardMarkup


@dataclass
class ChannelMetadata:
    """Per-call metadata for create_channel operations."""

    target_computer: str | None = None


class ContentFormat(StrEnum):
    """Authoring format of a message's content.

    Declared by the sender as content semantics; each adapter decides how (or
    whether) to render that format for its own platform.
    """

    PLAIN = "plain"
    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class MessageMetadata:
    """Per-call metadata for message operations."""

    reply_markup: Optional["InlineKeyboardMarkup"] = None
    parse_mode: str | None = None
    content_format: ContentFormat = ContentFormat.PLAIN
    message_thread_id: int | None = None
    raw_format: bool = False
    origin: str | None = None
    text_kind: TranscriptEntryKind | None = None
    channel_id: str | None = None
    title: str | None = None
    project_path: str | None = None
    subdir: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    platform_message_id: str | None = None
    generation_id: str | None = None
    caller_session_id: str | None = None
    caller_author_kind: str | None = None
    caller_author_display: str | None = None
    caller_agent_runtime: str | None = None
    caller_thinking_mode: str | None = None
    caller_machine_role: str | None = None
    caller_job_role: str | None = None
    caller_origin_prefix_len: int | None = None
    caller_origin_suffix_len: int | None = None
    human_email: str | None = None
    human_role: str | None = None
    origin_metadata: SessionOriginMetadata | None = None
    system_role: str | None = None
    job: str | None = None
    launch_intent: Optional["SessionLaunchIntent"] = None
    cleanup_trigger: str | None = None
    target_adapter_key: str | None = None
    reflection_actor_id: str | None = None
    reflection_actor_name: str | None = None
    reflection_actor_avatar_url: str | None = None
    reflection_origin: str | None = None


@dataclass(frozen=True)
class OriginRevivalContext:
    """Originating session identity recovered for native-form revive adoption."""

    project_path: str | None
    subdir: str | None
    title: str | None


@dataclass
class SessionLaunchIntent:
    """Normalized session launch intent (adapter boundary to core)."""

    kind: "SessionLaunchKind"
    agent: str | None = None
    thinking_mode: str | None = None
    message: str | None = None
    native_session_id: str | None = None
    dispatch_mode: "AgentDispatchMode | None" = None
    request_id: str | None = None
    entry_point: "SessionEntryPoint | None" = None
    job_role: str | None = None
    preferred_agent: str | None = None
    fixed_agent: str | None = None
    producer_agent: str | None = None
    decision_basis_digest: str | None = None
    accepted_at_origin: bool = False
    # Transient launch state, resolved before the session row is created and
    # consumed during bootstrap. It is deliberately excluded from the wire
    # representation: a remote target resolves its own model availability.
    resolved_model_flags: str | None = None

    def to_dict(self) -> JsonDict:
        """Serialize launch intent into a JSON-compatible dictionary."""
        return {
            "kind": self.kind.value,
            "agent": self.agent,
            "thinking_mode": self.thinking_mode,
            "message": self.message,
            "native_session_id": self.native_session_id,
            "dispatch_mode": self.dispatch_mode.value if self.dispatch_mode else None,
            "request_id": self.request_id,
            "entry_point": self.entry_point.value if self.entry_point else None,
            "job_role": self.job_role,
            "preferred_agent": self.preferred_agent,
            "fixed_agent": self.fixed_agent,
            "producer_agent": self.producer_agent,
            "decision_basis_digest": self.decision_basis_digest,
            "accepted_at_origin": self.accepted_at_origin,
        }

    @classmethod
    def from_dict(cls, data: JsonDict) -> "SessionLaunchIntent":
        """Create launch intent from a JSON-compatible dictionary."""
        if FIELD_KIND not in data or data[FIELD_KIND] is None:
            raise ValueError("launch_intent.kind is required")
        return cls(
            kind=SessionLaunchKind(str(data[FIELD_KIND])),
            agent=cast(str | None, data.get("agent")),
            thinking_mode=cast(str | None, data.get("thinking_mode")),
            message=cast(str | None, data.get("message")),
            native_session_id=cast(str | None, data.get("native_session_id")),
            dispatch_mode=(
                AgentDispatchMode(str(data["dispatch_mode"]))
                if data.get("dispatch_mode") is not None
                else (AgentDispatchMode.FIXED if data.get("agent") else AgentDispatchMode.AUTOMATIC)
            ),
            request_id=cast(str | None, data.get("request_id")),
            entry_point=(SessionEntryPoint(str(data["entry_point"])) if data.get("entry_point") is not None else None),
            job_role=cast(str | None, data.get("job_role")),
            preferred_agent=cast(str | None, data.get("preferred_agent")),
            fixed_agent=cast(str | None, data.get("fixed_agent")),
            producer_agent=cast(str | None, data.get("producer_agent")),
            decision_basis_digest=cast(str | None, data.get("decision_basis_digest")),
            accepted_at_origin=bool(data.get("accepted_at_origin", False)),
        )


class SessionLaunchKind(Enum):
    """Supported launch modes for session creation and resume."""

    EMPTY = "empty"
    AGENT = "agent"
    AGENT_THEN_MESSAGE = "agent_then_message"
    AGENT_RESUME = "agent_resume"


class AgentDispatchMode(StrEnum):
    """The caller's authority over a launch agent."""

    AUTOMATIC = "automatic"
    MANUAL_PREFERENCE = "manual_preference"
    FIXED = "fixed"


class SessionEntryPoint(StrEnum):
    """Closed vocabulary for fresh-session producers."""

    API_CREATE = "api_create"
    RUN_SESSION_API = "run_session_api"
    LIFECYCLE_RUNNER = "lifecycle_runner"
    GENERATED_TOOL_CALL = "generated_tool_call"
    INTEGRATION = "integration"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    CRON = "cron"
    SYSTEM = "system"


FIELD_KIND = "kind"


class CleanupTrigger(Enum):
    """When an ephemeral UI message should be removed."""

    NEXT_NOTICE = "next_notice"
    NEXT_TURN = "next_turn"


class SessionField(Enum):
    """Session field names used in updates/events."""

    ORIGIN_METADATA = "origin_metadata"
    TITLE = "title"
    PROJECT_PATH = "project_path"
    SUBDIR = "subdir"
    LAST_MESSAGE_SENT = "last_message_sent"
    LAST_MESSAGE_SENT_AT = "last_message_sent_at"
    LAST_PROJECTED_AT = "last_projected_at"
    LAST_PROJECTED_OUTPUT_DIGEST = "last_projected_output_digest"
    LAST_OUTPUT_RAW = "last_output_raw"
    LAST_OUTPUT_AT = "last_output_at"
    LAST_TOOL_DONE_AT = "last_tool_done_at"
    LAST_TOOL_USE_AT = "last_tool_use_at"
    LAST_CHECKPOINT_AT = "last_checkpoint_at"
    LAST_AGENT_STOP_AT = "last_agent_stop_at"
    TURN_ANCHOR_SHA = "turn_anchor_sha"


class TranscriptFormat(str, Enum):
    """Output format for session transcripts."""

    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class Session(SessionRecentOutputFields, SessionRecentToolFields):
    """Represents a tmux session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    title: str
    last_input_origin: str | None = None
    origin_metadata: SessionOriginMetadata = field(default_factory=lambda: cast(SessionOriginMetadata, {}))
    system_role: str | None = None
    job: str | None = None
    created_at: datetime | None = None
    last_activity: datetime | None = None
    closed_at: datetime | None = None
    project_path: str | None = None
    subdir: str | None = None
    description: str | None = None
    initiated_by_ai: bool = False
    initiator_session_id: str | None = None
    initiator_computer: str | None = None
    detached: bool = False
    output_message_id: str | None = None
    notification_sent: bool = False
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    tui_log_file: str | None = None
    tui_capture_started: bool = False
    human_email: str | None = None
    human_role: str | None = None
    principal: str | None = None
    lifecycle_status: str = "active"
    last_memory_extraction_at: datetime | None = None
    help_desk_processed_at: datetime | None = None
    relay_status: str | None = None
    relay_channel_id: str | None = None
    relay_started_at: datetime | None = None
    transcript_files: str = "[]"
    char_offset: int = 0
    visibility: str | None = "private"

    def get_origin_section(self, key: str) -> dict[str, object]:  # guard: loose-dict - JSON section
        """Get a platform section from origin_metadata."""
        section = self.origin_metadata.get(key)
        if isinstance(section, dict):
            return dict(section)
        return {}

    def to_dict(self) -> JsonDict:
        """Convert session to dictionary for JSON serialization."""
        data = cast(JsonDict, asdict(self))
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        if self.last_message_sent_at:
            data["last_message_sent_at"] = self.last_message_sent_at.isoformat()
        if self.last_projected_at:
            data["last_projected_at"] = self.last_projected_at.isoformat()
        if self.last_output_at:
            data["last_output_at"] = self.last_output_at.isoformat()
        if self.last_tool_done_at:
            data["last_tool_done_at"] = self.last_tool_done_at.isoformat()
        if self.last_tool_use_at:
            data["last_tool_use_at"] = self.last_tool_use_at.isoformat()
        if self.last_checkpoint_at:
            data["last_checkpoint_at"] = self.last_checkpoint_at.isoformat()
        if self.last_agent_stop_at:
            data["last_agent_stop_at"] = self.last_agent_stop_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        if self.last_memory_extraction_at:
            data["last_memory_extraction_at"] = self.last_memory_extraction_at.isoformat()
        if self.help_desk_processed_at:
            data["help_desk_processed_at"] = self.help_desk_processed_at.isoformat()
        if self.relay_started_at:
            data["relay_started_at"] = self.relay_started_at.isoformat()
        data["lifecycle_status"] = self.lifecycle_status
        data["origin_metadata"] = self.origin_metadata
        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, object],  # guard: loose-dict - JSON deserialization
    ) -> "Session":
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

        last_projected_at_raw = data.get("last_projected_at")
        last_projected_at = (
            parse_iso_datetime(last_projected_at_raw)
            if isinstance(last_projected_at_raw, str)
            else last_projected_at_raw
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
        last_agent_stop_at_raw = data.get("last_agent_stop_at")
        last_agent_stop_at = (
            parse_iso_datetime(last_agent_stop_at_raw)
            if isinstance(last_agent_stop_at_raw, str)
            else last_agent_stop_at_raw
        )

        # Parse origin_metadata from dict or keep empty
        origin_raw = data.get("origin_metadata")
        origin_metadata: dict[str, object] = {}  # guard: loose-dict - JSON blob
        if isinstance(origin_raw, dict):
            origin_metadata = dict(origin_raw)

        ia_val = data.get("initiated_by_ai")
        initiated_by_ai = bool(ia_val) if ia_val is not None else False

        notification_sent_val = data.get("notification_sent")
        notification_sent = bool(notification_sent_val) if notification_sent_val is not None else False

        detached_val = data.get("detached")
        detached = bool(detached_val) if detached_val is not None else False

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
            origin_metadata=origin_metadata,
            system_role=_get_optional_str("system_role"),
            job=_get_optional_str("job"),
            created_at=ensure_utc(created_at) if isinstance(created_at, datetime) else None,
            last_activity=ensure_utc(last_activity) if isinstance(last_activity, datetime) else None,
            closed_at=ensure_utc(closed_at) if isinstance(closed_at, datetime) else None,
            project_path=_get_optional_str("project_path"),
            subdir=_get_optional_str("subdir"),
            description=_get_optional_str("description"),
            initiated_by_ai=initiated_by_ai,
            initiator_session_id=_get_optional_str("initiator_session_id"),
            initiator_computer=_get_optional_str("initiator_computer"),
            detached=detached,
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
            last_projected_at=ensure_utc(last_projected_at) if isinstance(last_projected_at, datetime) else None,
            last_output_raw=_get_optional_str("last_output_raw"),
            last_output_at=ensure_utc(last_output_at) if isinstance(last_output_at, datetime) else None,
            last_tool_done_at=ensure_utc(last_tool_done_at) if isinstance(last_tool_done_at, datetime) else None,
            last_tool_use_at=ensure_utc(last_tool_use_at) if isinstance(last_tool_use_at, datetime) else None,
            last_checkpoint_at=ensure_utc(last_checkpoint_at) if isinstance(last_checkpoint_at, datetime) else None,
            last_agent_stop_at=ensure_utc(last_agent_stop_at) if isinstance(last_agent_stop_at, datetime) else None,
            turn_anchor_sha=_get_optional_str("turn_anchor_sha"),
            last_output_summary=_get_optional_str("last_output_summary"),
            last_output_digest=_get_optional_str("last_output_digest"),
            last_projected_output_digest=_get_optional_str("last_projected_output_digest"),
            working_slug=_get_optional_str("working_slug"),
            human_email=_get_optional_str("human_email"),
            human_role=_get_optional_str("human_role"),
            lifecycle_status=str(data.get("lifecycle_status") or "active"),
            last_memory_extraction_at=parse_iso_datetime(data.get("last_memory_extraction_at"))
            if isinstance(data.get("last_memory_extraction_at"), str)
            else None,
            help_desk_processed_at=parse_iso_datetime(data.get("help_desk_processed_at"))
            if isinstance(data.get("help_desk_processed_at"), str)
            else None,
            relay_status=_get_optional_str("relay_status"),
            relay_channel_id=_get_optional_str("relay_channel_id"),
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
