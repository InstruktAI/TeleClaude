"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Union, cast

from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.dates import parse_iso_datetime

# Event bus carries internal events (not user commands).
EventType = Literal[
    "agent_activity",
    "agent_availability",
    "agent_event",
    "agent_readiness_timeout",
    "agent_ready",
    "error",
    "operation.todo_create.completed",
    "operation.todo_integrate.completed",
    "operation.todo_prepare.completed",
    "operation.todo_rename.completed",
    "operation.todo_remove.completed",
    "operation.todo_work.completed",
    "operation.task_run.completed",
    "session_close_requested",
    "session_closed",
    "session_started",
    "session_status",
    "session_updated",
    "system_command",
    "voice_focus_set",
]


class AgentHookEvents(StrEnum):
    """Internal hook event vocabulary shared after provider normalization."""

    AGENT_ERROR = "error"
    AGENT_BLOCKED = "agent_blocked"
    AGENT_IDLE = "agent_idle"
    AGENT_SESSION_START = "session_start"
    AGENT_STOP = "agent_stop"
    AGENT_TURN_FAILED = "agent_turn_failed"
    CHECKPOINT_SEEN = "checkpoint_seen"
    NATIVE_METADATA_UPDATE = "native_metadata_update"
    NATIVE_SESSION_REFRESH = "native_session_refresh"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"


AgentHookEventType = AgentHookEvents


ALL_AGENT_HOOK_EVENTS: frozenset[AgentHookEventType] = frozenset(AgentHookEvents)
_DISTRESS_REASON_FIELD = "reason"
_DISTRESS_NOTIFICATION_TYPE_FIELD = "notification_type"
_DISTRESS_ERROR_FIELD = "error"
_DISTRESS_TERMINATION_REASON_FIELD = "terminationReason"
_DISTRESS_ERROR_MESSAGE_FIELD = "message"
_ATTENTION_PROVIDER_FIELD = "agent_name"
_ATTENTION_NATIVE_EVENT_FIELD = "native_event_type"
_ATTENTION_DETAILS_FIELD = "native_event_details"
_ATTENTION_OBSERVED_AT_FIELD = "received_at"
_ATTENTION_INGRESS_ID_FIELD = "receiver_ingress_id"
RECEIVER_HANDLED_HOOK_EVENTS: frozenset[AgentHookEventType] = frozenset(
    {
        AgentHookEvents.AGENT_ERROR,
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_IDLE,
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_TURN_FAILED,
        AgentHookEvents.PRE_TOOL_USE,
        AgentHookEvents.POST_TOOL_USE,
        AgentHookEvents.USER_PROMPT_SUBMIT,
    }
)


@dataclass(frozen=True)
class AgentSessionStartPayload:
    """Internal payload for agent session_start hook.

    guard: loose-dict - Agent hook data varies by agent.
    """

    raw: Mapping[str, object] = field(default_factory=dict)
    transcript_path: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class UserPromptSubmitPayload:
    """Internal payload for user prompt submission hook.

    guard: loose-dict - Agent hook data varies by agent.
    """

    prompt: str
    session_id: str | None = None
    transcript_path: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    source_computer: str | None = None


@dataclass(frozen=True)
class AgentOutputPayload:
    """Internal payload for rich incremental agent output.

    guard: loose-dict - Agent hook data varies by agent.
    """

    session_id: str | None = None
    transcript_path: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    source_computer: str | None = None


@dataclass(frozen=True)
class AgentStopPayload:
    """Internal payload for agent stop hook.

    guard: loose-dict - Agent hook data varies by agent.
    """

    session_id: str | None = None
    transcript_path: str | None = None
    prompt: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    source_computer: str | None = None
    native_turn_id: str | None = None


@dataclass(frozen=True)
class AgentIdlePayload:
    """Internal payload for a provider-observed completed native command.

    guard: loose-dict - Agent hook data varies by agent.
    """

    session_id: str | None = None
    transcript_path: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    source_computer: str | None = None


@dataclass(frozen=True)
class AgentDistressPayload:
    """Internal payload for a provider-reported blocked or failed turn."""

    session_id: str | None = None
    transcript_path: str | None = None
    source_computer: str | None = None
    reason: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)
    observation: "AgentAttentionObservation | None" = None


@dataclass(frozen=True)
class AgentAttentionObservation:
    """Provider evidence retained for a native attention occurrence."""

    provider: str | None
    native_event: str | None
    details: Mapping[str, object]
    observed_at: datetime | None
    ingress_id: str | None


AgentEventPayload = Union[
    AgentSessionStartPayload,
    UserPromptSubmitPayload,
    AgentOutputPayload,
    AgentStopPayload,
    AgentIdlePayload,
    AgentDistressPayload,
]


# Event types supported by build_agent_payload
# Additional AgentHookEventType values exist but have no payload builders yet
SUPPORTED_PAYLOAD_TYPES: set[AgentHookEventType] = {
    AgentHookEvents.AGENT_SESSION_START,
    AgentHookEvents.USER_PROMPT_SUBMIT,
    AgentHookEvents.AGENT_IDLE,
    AgentHookEvents.AGENT_STOP,
    AgentHookEvents.AGENT_BLOCKED,
    AgentHookEvents.AGENT_TURN_FAILED,
    AgentHookEvents.PRE_TOOL_USE,
    AgentHookEvents.POST_TOOL_USE,
}


def build_agent_payload(event_type: AgentHookEventType, data: Mapping[str, object]) -> AgentEventPayload:
    """Build typed agent payload from normalized hook data.

    Raises:
        ValueError: If event_type is not in SUPPORTED_PAYLOAD_TYPES
    """
    native_id = cast(str | None, data.get("session_id"))
    frozen_raw = MappingProxyType(dict(data))

    if event_type == AgentHookEvents.AGENT_SESSION_START:
        return AgentSessionStartPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            raw=frozen_raw,
        )

    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        return UserPromptSubmitPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            prompt=cast(str, data.get("prompt", "")),
            raw=frozen_raw,
            source_computer=cast(str | None, data.get("source_computer")),
        )

    if event_type == AgentHookEvents.AGENT_STOP:
        return AgentStopPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            prompt=cast(str | None, data.get("prompt")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    if event_type == AgentHookEvents.AGENT_IDLE:
        return AgentIdlePayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    if event_type in {
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_TURN_FAILED,
    }:
        return AgentDistressPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            source_computer=cast(str | None, data.get("source_computer")),
            reason=_distress_reason(data),
            raw=frozen_raw,
            observation=_build_attention_observation(data),
        )

    if event_type in {AgentHookEvents.PRE_TOOL_USE, AgentHookEvents.POST_TOOL_USE}:
        return AgentOutputPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    raise ValueError(
        f"Unsupported agent hook event_type '{event_type}' for payload building. "
        f"Supported types: {sorted(SUPPORTED_PAYLOAD_TYPES)}"
    )


def _distress_reason(data: Mapping[str, object]) -> str | None:
    """Extract the provider token that explains a normalized distress event."""
    for reason_field in (
        _DISTRESS_REASON_FIELD,
        _DISTRESS_NOTIFICATION_TYPE_FIELD,
        _DISTRESS_ERROR_FIELD,
        _DISTRESS_TERMINATION_REASON_FIELD,
    ):
        value = data.get(reason_field)
        if isinstance(value, str) and value:
            return value
        if reason_field == _DISTRESS_ERROR_FIELD and isinstance(value, Mapping):
            message = value.get(_DISTRESS_ERROR_MESSAGE_FIELD)
            if isinstance(message, str) and message:
                return message
    return None


def _build_attention_observation(data: Mapping[str, object]) -> AgentAttentionObservation:
    """Project receiver-owned native observation metadata into a typed payload."""
    details = data.get(_ATTENTION_DETAILS_FIELD)
    return AgentAttentionObservation(
        provider=_optional_string(data.get(_ATTENTION_PROVIDER_FIELD)),
        native_event=_optional_string(data.get(_ATTENTION_NATIVE_EVENT_FIELD)),
        details=MappingProxyType(dict(details)) if isinstance(details, Mapping) else MappingProxyType({}),
        observed_at=parse_iso_datetime(data.get(_ATTENTION_OBSERVED_AT_FIELD)),
        ingress_id=_optional_string(data.get(_ATTENTION_INGRESS_ID_FIELD)),
    )


def _optional_string(value: object) -> str | None:
    """Return a non-empty string from dynamic hook data."""
    return value if isinstance(value, str) and value else None


class TeleClaudeEvents:
    """Standard TeleClaude events that daemon handles.

    These events are emitted by adapters and handled by the daemon.
    Adapter-specific events (like 'help') are NOT included here.
    """

    # Events (facts)
    SESSION_STARTED: Literal["session_started"] = "session_started"
    SESSION_CLOSED: Literal["session_closed"] = "session_closed"  # Fact: session is now closed. Observer-only.
    SESSION_UPDATED: Literal["session_updated"] = "session_updated"  # Session fields updated in DB
    SESSION_STATUS: Literal["session_status"] = "session_status"  # Canonical lifecycle status transition
    AGENT_AVAILABILITY: Literal["agent_availability"] = "agent_availability"  # Agent availability changed
    AGENT_READY: Literal["agent_ready"] = "agent_ready"  # Fact: normalized runtime start was observed.
    AGENT_READINESS_TIMEOUT: Literal["agent_readiness_timeout"] = (
        "agent_readiness_timeout"  # Fact: agent TUI did not reach ready prompt within timeout.
    )
    AGENT_EVENT: Literal["agent_event"] = "agent_event"  # Agent events (title change, etc.)
    AGENT_ACTIVITY: Literal["agent_activity"] = (
        "agent_activity"  # Agent activity events (pre_tool_use, agent_stop, etc.)
    )
    ERROR: Literal["error"] = "error"

    # Intents (commands)
    SESSION_CLOSE_REQUESTED: Literal["session_close_requested"] = (
        "session_close_requested"  # Intent: close this session. Triggers terminate_session exactly once.
    )


ErrorSeverity = Literal["warning", "error", "critical"]


def parse_command_string(command_str: str) -> tuple[str | None, list[str]]:
    """Parse command string into event name and arguments.

    Used by adapters that receive raw command strings (e.g., Redis, API API).
    Telegram adapter doesn't need this - python-telegram-bot parses for us.

    Args:
        command_str: Raw command string (e.g., "/new_session My Project")

    Returns:
        Tuple of (event_name, args_list)
        Returns (None, []) if command is empty

    Examples:
        >>> parse_command_string("/new_session My Project")
        ("new_session", ["My", "Project"])
        >>> parse_command_string("/claude -m 'Hello'")
        ("claude", ["-m", "Hello"])
        >>> parse_command_string("new_session My Project")
        ("new_session", ["My", "Project"])
    """
    # Use shlex.split for proper shell-like parsing (handles quotes)
    try:
        parts = shlex.split(command_str.strip())
    except ValueError:
        # Invalid quotes/syntax - fall back to simple split
        parts = command_str.strip().split()

    if not parts:
        return None, []

    # Extract command name (remove leading slash if present)
    cmd_name = parts[0].lstrip("/")

    # Extract arguments (rest of the parts)
    args = parts[1:] if len(parts) > 1 else []

    return cmd_name, args


# Event context models (dataclass for type safety)


@dataclass(frozen=True)
class MessageEventContext:
    """Context for message events."""

    session_id: str
    text: str = ""


@dataclass(frozen=True)
class FileEventContext:
    """Context for file upload events."""

    session_id: str
    file_path: str = ""
    filename: str = ""
    caption: str | None = None
    file_size: int = 0


@dataclass(frozen=True)
class VoiceEventContext:
    """Context for voice message events."""

    session_id: str
    file_path: str = ""
    duration: float | None = None
    message_id: str | None = None
    message_thread_id: int | None = None
    origin: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    voice_transcription_id: int | None = None
    notice_message_id: str | None = None


@dataclass(frozen=True)
class SessionLifecycleContext:
    """Context for session lifecycle events."""

    session_id: str


class SystemCommand(StrEnum):
    """Closed vocabulary for system commands carrying a validated typed payload.

    A daemon-to-daemon system command outside this vocabulary keeps today's
    bare-string path (no payload validation, no narrowing).
    """

    SESSION_OUTPUT_STOPPED = "session_output_stopped"


@dataclass(frozen=True)
class SessionOutputStoppedPayload:
    """Validated payload for `SystemCommand.SESSION_OUTPUT_STOPPED`."""

    session_id: str
    last_output_stop_at: str

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - wire payload
        """Serialize for transport as system-command args."""
        return {"session_id": self.session_id, "last_output_stop_at": self.last_output_stop_at}

    @classmethod
    def from_dict(cls, data: object) -> "SessionOutputStoppedPayload | None":  # guard: loose-dict
        """Validate a decoded args mapping, or return None when malformed."""
        if not isinstance(data, dict):
            return None
        session_id = data.get("session_id")
        last_output_stop_at = data.get("last_output_stop_at")
        if not isinstance(session_id, str) or not session_id:
            return None
        if not isinstance(last_output_stop_at, str) or not last_output_stop_at:
            return None
        if parse_iso_datetime(last_output_stop_at) is None:
            return None
        return cls(session_id=session_id, last_output_stop_at=last_output_stop_at)


@dataclass(frozen=True)
class SystemCommandContext:
    """Context for system commands (no session_id)."""

    command: str = ""
    from_computer: str = "unknown"
    payload: SessionOutputStoppedPayload | None = None


@dataclass(frozen=True)
class VoiceFocusSetContext:
    """Local-only event: a person's voice focus was durably set.

    Carries `focus_id` only — never a person slug, email, or platform id.
    The Discord adapter subscribes to play the newly focused session's
    current reply immediately; core emits this without importing any
    adapter module.
    """

    focus_id: str
    session_id: str
    basis: str
    set_at: str


@dataclass(frozen=True)
class AgentEventContext:
    """Context for Agent events (from hooks)."""

    session_id: str
    data: AgentEventPayload
    event_type: AgentHookEventType


@dataclass(frozen=True)
class SessionUpdatedContext:
    """Context for session_updated events.

    guard: loose-dict - Dynamic session field updates.
    """

    session_id: str
    updated_fields: Mapping[str, object]


@dataclass(frozen=True)
class SessionStatusContext:
    """Context for canonical session lifecycle status transition events.

    Canonical contract fields (ucap-truthful-session-status):
      status: Canonical lifecycle status value (accepted, active,
              active_output, completed, error, closed).
      reason: Reason code for the transition.
      last_activity_at: ISO 8601 UTC timestamp of last known activity (optional).
      message_intent: Routing intent (ctrl_status).
      delivery_scope: Routing scope (CTRL for all status events).
    """

    session_id: str
    status: str
    reason: str
    timestamp: str
    last_activity_at: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


@dataclass(frozen=True)
class AgentAvailabilityContext:
    """Context for agent availability changes broadcast to clients."""

    agent: str
    status: AgentAvailabilityStatus | None = None
    status_until: str | None = None
    reason: str | None = None
    error: str | None = None
    model: str | None = None
    model_status: AgentAvailabilityStatus | None = None
    model_status_until: str | None = None
    model_reason: str | None = None


@dataclass(frozen=True)
class BaseAgentActivityEvent:
    """Base class for typed real-time activity events."""

    session_id: str
    event_type: AgentHookEventType
    timestamp: str | None = None
    canonical_type: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


@dataclass(frozen=True)
class UserPromptSubmitActivityEvent(BaseAgentActivityEvent):
    """Real-time user prompt submit activity."""


@dataclass(frozen=True)
class ToolUseActivityEvent(BaseAgentActivityEvent):
    """Real-time tool-use activity."""

    tool_name: str | None = None
    tool_preview: str | None = None


@dataclass(frozen=True)
class AgentStopActivityEvent(BaseAgentActivityEvent):
    """Real-time turn completion activity."""

    summary: str | None = None
    message: str | None = None


type AgentActivityEvent = UserPromptSubmitActivityEvent | ToolUseActivityEvent | AgentStopActivityEvent


@dataclass(frozen=True)
class ErrorEventContext:
    """Context for error events.

    guard: loose-dict - Error detail data varies by error.
    """

    session_id: str | None
    message: str
    source: str | None = None
    details: Mapping[str, object] | None = None
    severity: ErrorSeverity = "error"
    retryable: bool = False
    code: str | None = None


# Domain event payloads for fire-and-forget mutation completion signals


@dataclass(frozen=True)
class AgentRestartDispatchedPayload:
    """Emitted after successful agent restart dispatch."""

    session_id: str


@dataclass(frozen=True)
class SessionCloseCompletedPayload:
    """Emitted when close processing finishes for a session."""

    session_id: str


@dataclass(frozen=True)
class SessionEscalatedPayload:
    """Emitted when session escalation is initiated."""

    session_id: str


@dataclass(frozen=True)
class JobStartedPayload:
    """Emitted when a background job starts execution."""

    job_name: str


@dataclass(frozen=True)
class JobCompletedPayload:
    """Emitted when a background job completes successfully."""

    job_name: str


@dataclass(frozen=True)
class JobFailedPayload:
    """Emitted when a background job fails."""

    job_name: str
    error: str | None = None


@dataclass(frozen=True)
class NotificationClaimedPayload:
    """Emitted when a notification is claimed by an agent."""

    notification_id: int
    agent_id: str


@dataclass(frozen=True)
class NotificationResolvedPayload:
    """Emitted when a notification is resolved."""

    notification_id: int


@dataclass(frozen=True)
class OperationCompletedContext:
    """Emitted when a long-running operation reaches a terminal state (completed or failed)."""

    operation_id: str
    error: str | None = None


# Union of all event context types (for adapter_client handler signatures)
EventContext = (
    AgentActivityEvent
    | AgentAvailabilityContext
    | AgentEventContext
    | AgentRestartDispatchedPayload
    | ErrorEventContext
    | JobCompletedPayload
    | JobFailedPayload
    | JobStartedPayload
    | MessageEventContext
    | NotificationClaimedPayload
    | NotificationResolvedPayload
    | OperationCompletedContext
    | SessionCloseCompletedPayload
    | SessionEscalatedPayload
    | SessionLifecycleContext
    | SessionStatusContext
    | SessionUpdatedContext
    | SystemCommandContext
    | VoiceFocusSetContext
)
