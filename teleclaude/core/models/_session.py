"""Session model and related types for TeleClaude."""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Optional, cast

from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.injected_text import TranscriptEntryKind
from teleclaude.core.session_status import AgentStatusReason, AgentStatusValue, TurnNotificationRecord
from teleclaude.session_fields import SessionRecentOutputFields, SessionRecentToolFields

from ._types import (
    CONFINEMENT_PROFILE_KEY,
    CONFINEMENT_SECTION,
    JsonDict,
    SessionOriginMetadata,
    to_json_dict,
    to_json_value,
)

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
    company: str | None = None
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
    candidate_order: tuple[str, ...] | None = None
    decision_basis_digest: str | None = None
    accepted_at_origin: bool = False
    # Transient launch state, resolved before the session row is created and
    # consumed during bootstrap. It is deliberately excluded from the wire
    # representation: a remote target resolves its own model availability.
    resolved_model_flags: str | None = None
    command_input_source_text: str | None = None

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
            "candidate_order": list(self.candidate_order) if self.candidate_order is not None else None,
            "decision_basis_digest": self.decision_basis_digest,
            "accepted_at_origin": self.accepted_at_origin,
            "command_input_source_text": self.command_input_source_text,
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
            candidate_order=(
                tuple(cast(list[str], data["candidate_order"])) if data.get("candidate_order") is not None else None
            ),
            decision_basis_digest=cast(str | None, data.get("decision_basis_digest")),
            accepted_at_origin=bool(data.get("accepted_at_origin", False)),
            command_input_source_text=cast(str | None, data.get("command_input_source_text")),
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
    PERSONAL_ASSISTANT_LAUNCH = "personal_assistant_launch"
    LIFECYCLE_RUNNER = "lifecycle_runner"
    GENERATED_TOOL_CALL = "generated_tool_call"
    INTEGRATION = "integration"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    CRON = "cron"
    SYSTEM = "system"
    AGENT_HANDOFF = "agent_handoff"
    PROCEDURE_ACTIVATION = "procedure_activation"


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
    LAST_OUTPUT_SUMMARY = "last_output_summary"
    LAST_OUTPUT_STOP_AT = "last_output_stop_at"
    LAST_OUTPUT_AT = "last_output_at"
    LAST_TOOL_DONE_AT = "last_tool_done_at"
    LAST_TOOL_USE_AT = "last_tool_use_at"
    LAST_CHECKPOINT_AT = "last_checkpoint_at"
    LAST_AGENT_STOP_AT = "last_agent_stop_at"
    LAST_AGENT_IDLE_AT = "last_agent_idle_at"
    LIFECYCLE_STATUS = "lifecycle_status"
    RUNTIME_ACTIVITY_AT = "runtime_activity_at"
    AGENT_STATUS = "agent_status"
    AGENT_STATUS_REASON = "agent_status_reason"
    AGENT_STATUS_SINCE = "agent_status_since"
    AGENT_STATUS_VERSION = "agent_status_version"
    OPEN_TOOL_CALLS = "open_tool_calls"
    TURN_NOTIFICATIONS_SENT = "turn_notifications_sent"
    LIFECYCLE_TRANSITIONED_AT = "lifecycle_transitioned_at"
    TURN_ANCHOR_SHA = "turn_anchor_sha"
    RELAY_TARGETS = "relay_targets"
    RELAY_EXCHANGE = "relay_exchange"


class TranscriptFormat(str, Enum):
    """Output format for session transcripts."""

    MARKDOWN = "markdown"
    HTML = "html"


class RelayStatus(StrEnum):
    """A session's escalation relay state; a session not relaying stores none."""

    ACTIVE = "active"


class RelayExchangeRole(StrEnum):
    """Who spoke in an escalation relay's exchange."""

    VISITOR = "Customer"
    ADMIN = "Admin"


class RelayRecordField(StrEnum):
    """Persisted key names of a relay target and an exchange entry."""

    PERSON = "person"
    CHANNEL = "channel"
    TARGET = "target"
    MESSAGE_IDS = "message_ids"
    ROLE = "role"
    NAME = "name"
    CONTENT = "content"


@dataclass(frozen=True)
class RelayTarget:
    """One notified admin's side of an escalation relay.

    ``channel`` is the messaging channel the admin was reached on, ``target``
    that channel's address for them, and ``message_ids`` every relay message
    sent to them there, any of which they may reply to.
    """

    person: str
    channel: str
    target: str
    message_ids: tuple[str, ...] = ()

    def with_message(self, message_id: str) -> "RelayTarget":
        """This target with one more relay message recorded."""
        return RelayTarget(self.person, self.channel, self.target, (*self.message_ids, message_id))

    def to_dict(self) -> JsonDict:
        """Serialize to the stored record."""
        return {
            RelayRecordField.PERSON.value: self.person,
            RelayRecordField.CHANNEL.value: self.channel,
            RelayRecordField.TARGET.value: self.target,
            RelayRecordField.MESSAGE_IDS.value: list(self.message_ids),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "RelayTarget | None":
        """Deserialize a stored record; one missing an address or with malformed message ids is no target."""
        person, channel, target = (raw.get(key) for key in _RELAY_TARGET_ADDRESS_FIELDS)
        if not (isinstance(person, str) and isinstance(channel, str) and isinstance(target, str)):
            return None
        ids = raw.get(RelayRecordField.MESSAGE_IDS.value, [])
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            return None
        return cls(person=person, channel=channel, target=target, message_ids=tuple(ids))


_RELAY_TARGET_ADDRESS_FIELDS = (RelayRecordField.PERSON, RelayRecordField.CHANNEL, RelayRecordField.TARGET)


@dataclass(frozen=True)
class RelayExchangeEntry:
    """One message of an escalation relay's exchange between the visitor and the admins."""

    role: RelayExchangeRole
    name: str
    content: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to the stored record, which is also the relay-context message shape."""
        return {
            RelayRecordField.ROLE.value: self.role.value,
            RelayRecordField.NAME.value: self.name,
            RelayRecordField.CONTENT.value: self.content,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "RelayExchangeEntry | None":
        """Deserialize a stored record; an unknown role is no entry."""
        name, content = raw.get(RelayRecordField.NAME.value), raw.get(RelayRecordField.CONTENT.value)
        try:
            role = RelayExchangeRole(str(raw.get(RelayRecordField.ROLE.value)))
        except ValueError:
            return None
        if not isinstance(name, str) or not isinstance(content, str):
            return None
        return cls(role=role, name=name, content=content)


def encode_relay_targets(targets: tuple[RelayTarget, ...]) -> str:
    """The stored text of a relay's targets."""
    return json.dumps([target.to_dict() for target in targets])


def encode_relay_exchange(exchange: tuple[RelayExchangeEntry, ...]) -> str:
    """The stored text of a relay's exchange."""
    return json.dumps([entry.to_dict() for entry in exchange])


_NO_RECORDS_TEXT = ""


class MalformedRelayRecord(ValueError):
    """A session's stored relay record is present but not a valid relay record."""


_MALFORMED_RELAY_RECORD = "malformed {field} record: {reason}"
_NOT_A_LIST = "not a list of records"
_INVALID_ENTRY = "an entry is not a valid record"


def _decoded_records(raw: object, field: SessionField) -> list[Mapping[str, object]]:
    """The records of a stored relay field; absent is none, anything present must be a list of records."""
    if raw is None or raw == _NO_RECORDS_TEXT:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedRelayRecord(_MALFORMED_RELAY_RECORD.format(field=field.value, reason=str(exc))) from exc
    if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
        raise MalformedRelayRecord(_MALFORMED_RELAY_RECORD.format(field=field.value, reason=_NOT_A_LIST))
    return list(raw)


def decode_relay_targets(raw: object) -> tuple[RelayTarget, ...]:
    """A relay's targets from their stored text or list; a malformed record raises ``MalformedRelayRecord``."""
    decoded = [RelayTarget.from_dict(item) for item in _decoded_records(raw, SessionField.RELAY_TARGETS)]
    if any(target is None for target in decoded):
        raise MalformedRelayRecord(
            _MALFORMED_RELAY_RECORD.format(field=SessionField.RELAY_TARGETS.value, reason=_INVALID_ENTRY)
        )
    return tuple(target for target in decoded if target is not None)


def decode_relay_exchange(raw: object) -> tuple[RelayExchangeEntry, ...]:
    """A relay's exchange from its stored text or list; a malformed record raises ``MalformedRelayRecord``."""
    decoded = [RelayExchangeEntry.from_dict(item) for item in _decoded_records(raw, SessionField.RELAY_EXCHANGE)]
    if any(entry is None for entry in decoded):
        raise MalformedRelayRecord(
            _MALFORMED_RELAY_RECORD.format(field=SessionField.RELAY_EXCHANGE.value, reason=_INVALID_ENTRY)
        )
    return tuple(entry for entry in decoded if entry is not None)


@dataclass
class Session(SessionRecentOutputFields, SessionRecentToolFields):
    """Represents a tmux session."""

    session_id: str
    computer_name: str
    tmux_session_name: str
    title: str
    last_input_origin: str | None = None
    origin_metadata: JsonDict = field(default_factory=dict)
    system_role: str | None = None
    job: str | None = None
    company: str | None = None
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
    turn_notifications_sent: frozenset[TurnNotificationRecord] = field(default_factory=frozenset)
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    tui_log_file: str | None = None
    tui_capture_started: bool = False
    human_email: str | None = None
    human_role: str | None = None
    principal: str | None = None
    lifecycle_status: str = "initializing"
    runtime_start_observed: bool = False
    runtime_activity_at: datetime | None = None
    agent_status: AgentStatusValue = AgentStatusValue.UNKNOWN
    agent_status_reason: AgentStatusReason | None = None
    agent_status_since: datetime | None = None
    agent_status_version: int = 0
    open_tool_calls: frozenset[str] = field(default_factory=frozenset)
    lifecycle_transitioned_at: datetime | None = None
    lifecycle_transition_reason: str | None = None
    last_memory_extraction_at: datetime | None = None
    help_desk_processed_at: datetime | None = None
    relay_status: str | None = None
    relay_channel_id: str | None = None
    relay_started_at: datetime | None = None
    relay_targets: tuple[RelayTarget, ...] = ()
    relay_exchange: tuple[RelayExchangeEntry, ...] = ()
    transcript_files: str = "[]"
    char_offset: int = 0
    visibility: str | None = "private"

    def get_origin_section(self, key: str) -> JsonDict:
        """Get a platform section from origin_metadata."""
        section = self.origin_metadata.get(key)
        if isinstance(section, dict):
            return dict(section)
        return {}

    @property
    def confinement_profile(self) -> str | None:
        """The launch profile this session was confined to when it was created, if any."""
        profile = self.get_origin_section(CONFINEMENT_SECTION).get(CONFINEMENT_PROFILE_KEY)
        return profile if isinstance(profile, str) else None

    def to_dict(self) -> JsonDict:
        """Convert session to dictionary for JSON serialization."""
        data = cast(JsonDict, asdict(self))
        data["origin_metadata"] = to_json_dict(self.origin_metadata)
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        if self.last_activity:
            data["last_activity"] = self.last_activity.isoformat()
        if self.runtime_activity_at:
            data["runtime_activity_at"] = self.runtime_activity_at.isoformat()
        if self.agent_status_since:
            data[SessionField.AGENT_STATUS_SINCE.value] = self.agent_status_since.isoformat()
        data[SessionField.AGENT_STATUS.value] = self.agent_status.value
        data[SessionField.AGENT_STATUS_REASON.value] = (
            self.agent_status_reason.value if self.agent_status_reason else None
        )
        data[SessionField.OPEN_TOOL_CALLS.value] = to_json_value(sorted(self.open_tool_calls))
        data[SessionField.TURN_NOTIFICATIONS_SENT.value] = to_json_value(
            sorted(record.value for record in self.turn_notifications_sent)
        )
        if self.lifecycle_transitioned_at:
            data["lifecycle_transitioned_at"] = self.lifecycle_transitioned_at.isoformat()
        if self.last_message_sent_at:
            data["last_message_sent_at"] = self.last_message_sent_at.isoformat()
        if self.last_input_written_at:
            data["last_input_written_at"] = self.last_input_written_at.isoformat()
        if self.last_projected_at:
            data["last_projected_at"] = self.last_projected_at.isoformat()
        if self.last_output_at:
            data["last_output_at"] = self.last_output_at.isoformat()
        if self.last_output_stop_at:
            data["last_output_stop_at"] = self.last_output_stop_at.isoformat()
        if self.last_tool_done_at:
            data["last_tool_done_at"] = self.last_tool_done_at.isoformat()
        if self.last_tool_use_at:
            data["last_tool_use_at"] = self.last_tool_use_at.isoformat()
        if self.last_checkpoint_at:
            data["last_checkpoint_at"] = self.last_checkpoint_at.isoformat()
        if self.last_agent_stop_at:
            data["last_agent_stop_at"] = self.last_agent_stop_at.isoformat()
        if self.last_agent_idle_at:
            data["last_agent_idle_at"] = self.last_agent_idle_at.isoformat()
        if self.closed_at:
            data["closed_at"] = self.closed_at.isoformat()
        if self.last_memory_extraction_at:
            data["last_memory_extraction_at"] = self.last_memory_extraction_at.isoformat()
        if self.help_desk_processed_at:
            data["help_desk_processed_at"] = self.help_desk_processed_at.isoformat()
        if self.relay_started_at:
            data["relay_started_at"] = self.relay_started_at.isoformat()
        data[SessionField.RELAY_TARGETS.value] = to_json_value([target.to_dict() for target in self.relay_targets])
        data[SessionField.RELAY_EXCHANGE.value] = to_json_value([entry.to_dict() for entry in self.relay_exchange])
        data["lifecycle_status"] = self.lifecycle_status
        return data

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],  # guard: loose-dict - JSON deserialization
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
        last_output_stop_at_raw = data.get("last_output_stop_at")
        last_output_stop_at = (
            parse_iso_datetime(last_output_stop_at_raw)
            if isinstance(last_output_stop_at_raw, str)
            else last_output_stop_at_raw
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
        last_agent_idle_at_raw = data.get("last_agent_idle_at")
        last_agent_idle_at = (
            parse_iso_datetime(last_agent_idle_at_raw)
            if isinstance(last_agent_idle_at_raw, str)
            else last_agent_idle_at_raw
        )

        # Parse origin_metadata from dict or keep empty
        origin_raw = data.get("origin_metadata")
        origin_metadata: JsonDict = {}
        if isinstance(origin_raw, dict):
            origin_metadata = to_json_dict(origin_raw)

        ia_val = data.get("initiated_by_ai")
        initiated_by_ai = bool(ia_val) if ia_val is not None else False

        detached_val = data.get("detached")
        detached = bool(detached_val) if detached_val is not None else False

        tui_capture_started_val = data.get("tui_capture_started")
        tui_capture_started = bool(tui_capture_started_val) if tui_capture_started_val is not None else False

        def _get_optional_str(key: str) -> str | None:
            value = data.get(key)
            return str(value) if value is not None else None

        turn_notifications_raw = data.get(SessionField.TURN_NOTIFICATIONS_SENT.value, [])
        turn_notifications_sent = frozenset(
            TurnNotificationRecord(record) for record in cast(list[str], turn_notifications_raw)
        )
        raw_agent_status_version = data.get(SessionField.AGENT_STATUS_VERSION.value)

        return cls(
            session_id=_get_optional_str("session_id") or "",
            computer_name=_get_optional_str("computer_name") or "",
            tmux_session_name=_get_optional_str("tmux_session_name") or "",
            title=_get_optional_str("title") or "",
            origin_metadata=origin_metadata,
            system_role=_get_optional_str("system_role"),
            job=_get_optional_str("job"),
            company=_get_optional_str("company"),
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
            turn_notifications_sent=turn_notifications_sent,
            native_session_id=_get_optional_str("native_session_id"),
            native_log_file=_get_optional_str("native_log_file"),
            active_agent=_get_optional_str("active_agent"),
            thinking_mode=_get_optional_str("thinking_mode"),
            tui_log_file=_get_optional_str("tui_log_file"),
            tui_capture_started=tui_capture_started,
            last_message_sent=_get_optional_str("last_message_sent"),
            last_input=_get_optional_str("last_input"),
            last_input_written_at=parse_iso_datetime(raw_written_at)
            if isinstance(raw_written_at := data.get("last_input_written_at"), str)
            else None,
            last_message_sent_at=ensure_utc(last_message_sent_at)
            if isinstance(last_message_sent_at, datetime)
            else None,
            last_projected_at=ensure_utc(last_projected_at) if isinstance(last_projected_at, datetime) else None,
            last_output_raw=_get_optional_str("last_output_raw"),
            last_output_stop_at=ensure_utc(last_output_stop_at) if isinstance(last_output_stop_at, datetime) else None,
            last_output_at=ensure_utc(last_output_at) if isinstance(last_output_at, datetime) else None,
            last_tool_done_at=ensure_utc(last_tool_done_at) if isinstance(last_tool_done_at, datetime) else None,
            last_tool_use_at=ensure_utc(last_tool_use_at) if isinstance(last_tool_use_at, datetime) else None,
            last_checkpoint_at=ensure_utc(last_checkpoint_at) if isinstance(last_checkpoint_at, datetime) else None,
            last_agent_stop_at=ensure_utc(last_agent_stop_at) if isinstance(last_agent_stop_at, datetime) else None,
            last_agent_idle_at=ensure_utc(last_agent_idle_at) if isinstance(last_agent_idle_at, datetime) else None,
            turn_anchor_sha=_get_optional_str("turn_anchor_sha"),
            last_output_summary=_get_optional_str("last_output_summary"),
            last_output_digest=_get_optional_str("last_output_digest"),
            last_projected_output_digest=_get_optional_str("last_projected_output_digest"),
            command=_get_optional_str("command"),
            working_slug=_get_optional_str("working_slug"),
            human_email=_get_optional_str("human_email"),
            human_role=_get_optional_str("human_role"),
            lifecycle_status=str(data.get("lifecycle_status") or "initializing"),
            runtime_start_observed=bool(data.get("runtime_start_observed", False)),
            runtime_activity_at=parse_iso_datetime(data["runtime_activity_at"])
            if isinstance(data.get("runtime_activity_at"), str)
            else None,
            agent_status=AgentStatusValue(
                str(data.get(SessionField.AGENT_STATUS.value, AgentStatusValue.UNKNOWN.value))
            ),
            agent_status_reason=(
                AgentStatusReason(str(data[SessionField.AGENT_STATUS_REASON.value]))
                if data.get(SessionField.AGENT_STATUS_REASON.value)
                else None
            ),
            agent_status_since=parse_iso_datetime(data[SessionField.AGENT_STATUS_SINCE.value])
            if isinstance(data.get(SessionField.AGENT_STATUS_SINCE.value), str)
            else None,
            agent_status_version=raw_agent_status_version if isinstance(raw_agent_status_version, int) else 0,
            open_tool_calls=frozenset(cast(list[str], data.get(SessionField.OPEN_TOOL_CALLS.value, []))),
            lifecycle_transitioned_at=parse_iso_datetime(data["lifecycle_transitioned_at"])
            if isinstance(data.get("lifecycle_transitioned_at"), str)
            else None,
            lifecycle_transition_reason=str(data.get("lifecycle_transition_reason"))
            if data.get("lifecycle_transition_reason")
            else None,
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
            relay_targets=decode_relay_targets(data.get(SessionField.RELAY_TARGETS.value)),
            relay_exchange=decode_relay_exchange(data.get(SessionField.RELAY_EXCHANGE.value)),
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
