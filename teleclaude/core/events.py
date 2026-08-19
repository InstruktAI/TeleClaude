"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Union, cast

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
]

# Internal hook event vocabulary — only events we ingest and process.
AgentHookEventType = Literal[
    "agent_stop",
    "checkpoint_seen",
    "error",
    "native_metadata_update",
    "native_session_refresh",
    "session_start",
    "tool_use",
    "user_prompt_submit",
]


class AgentHookEvents:
    """Internal hook event vocabulary and external→internal ingestion map."""

    AGENT_ERROR: AgentHookEventType = "error"
    AGENT_SESSION_START: AgentHookEventType = "session_start"
    AGENT_STOP: AgentHookEventType = "agent_stop"
    CHECKPOINT_SEEN: AgentHookEventType = "checkpoint_seen"
    NATIVE_METADATA_UPDATE: AgentHookEventType = "native_metadata_update"
    NATIVE_SESSION_REFRESH: AgentHookEventType = "native_session_refresh"
    TOOL_USE: AgentHookEventType = "tool_use"
    USER_PROMPT_SUBMIT: AgentHookEventType = "user_prompt_submit"

    # External-agent hook signatures. Documents the input shape each agent CLI emits.
    # None = signature is known to exist but is not ingested.
    HOOK_EVENT_MAP: Mapping[str, Mapping[str, AgentHookEventType | None]] = MappingProxyType(
        {
            "claude": MappingProxyType(
                {
                    "PostToolUse": None,
                    "PostToolUseFailure": None,
                    "PreCompact": None,
                    "PreToolUse": TOOL_USE,
                    "SessionEnd": None,
                    "SessionStart": AGENT_SESSION_START,
                    "Stop": AGENT_STOP,
                    "SubagentStart": None,
                    "SubagentStop": None,
                    "UserPromptSubmit": USER_PROMPT_SUBMIT,
                }
            ),
            # Antigravity lifecycle predicates are evaluated by AgyAdapter before
            # this catalog entry reaches the shared receiver path.
            "gemini": MappingProxyType(
                {
                    "PreInvocation": AGENT_SESSION_START,
                    "PreToolUse": TOOL_USE,
                    "Stop": AGENT_STOP,
                    "SessionEnd": None,
                    "PostInvocation": None,
                    "PostToolUse": None,
                }
            ),
            "codex": MappingProxyType(
                {
                    "PermissionRequest": None,
                    "PostToolUse": None,
                    "PreToolUse": TOOL_USE,
                    "SessionStart": AGENT_SESSION_START,
                    "Stop": AGENT_STOP,
                    "UserPromptSubmit": USER_PROMPT_SUBMIT,
                }
            ),
            # DeepSeek Harness emits Claude Code style hook names (dsh-hooks
            # plugin fork); StopFailure is the DSH analog of an errored turn.
            "deepseek": MappingProxyType(
                {
                    "PostToolBatch": None,
                    "PostToolUse": None,
                    "PostToolUseFailure": None,
                    "PreToolUse": TOOL_USE,
                    "SessionEnd": None,
                    "SessionStart": AGENT_SESSION_START,
                    "Stop": AGENT_STOP,
                    "StopFailure": AGENT_ERROR,
                    "SubagentEnd": None,
                    "SubagentStart": None,
                    "UserPromptSubmit": USER_PROMPT_SUBMIT,
                }
            ),
        }
    )

    ALL: set[AgentHookEventType] = {
        AGENT_ERROR,
        AGENT_SESSION_START,
        AGENT_STOP,
        CHECKPOINT_SEEN,
        NATIVE_METADATA_UPDATE,
        NATIVE_SESSION_REFRESH,
        TOOL_USE,
        USER_PROMPT_SUBMIT,
    }
    RECEIVER_HANDLED: frozenset[AgentHookEventType] = frozenset(
        {
            AGENT_ERROR,
            AGENT_SESSION_START,
            AGENT_STOP,
            TOOL_USE,
            USER_PROMPT_SUBMIT,
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


AgentEventPayload = Union[
    AgentSessionStartPayload,
    UserPromptSubmitPayload,
    AgentOutputPayload,
    AgentStopPayload,
]


# Event types supported by build_agent_payload
# Additional AgentHookEventType values exist but have no payload builders yet
SUPPORTED_PAYLOAD_TYPES: set[AgentHookEventType] = {
    AgentHookEvents.AGENT_SESSION_START,
    AgentHookEvents.USER_PROMPT_SUBMIT,
    AgentHookEvents.AGENT_STOP,
    AgentHookEvents.TOOL_USE,
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

    if event_type == AgentHookEvents.TOOL_USE:
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


# UI commands mapping (intentionally lowercase - not a constant despite dict type)
UiCommands = {
    "agent_restart": "Restart generic agent session",
    "agent_resume": "Resume an AI agent session",
    "claude": "Start Claude (alias for /agent claude)",
    "claude_plan": "Navigate to Claude plan mode",
    "gemini": "Start Gemini (alias for /agent gemini)",
    "codex": "Start Codex (alias for /agent codex)",
    "backspace": "Send BACKSPACE key (optional count)",
    "cancel": "Send CTRL+C to interrupt current command",
    "cancel2x": "Send CTRL+C twice (for stubborn programs)",
    "ctrl": "Send CTRL+key (e.g., /ctrl d for CTRL+D)",
    "enter": "Send ENTER key",
    "escape": "Send ESC key (exit Vim insert mode, etc.)",
    "escape2x": "Send ESC twice (for Agent, etc.)",
    "help": "Show help message",
    "key_down": "Send DOWN arrow key (optional repeat count)",
    "key_left": "Send LEFT arrow key (optional repeat count)",
    "key_right": "Send RIGHT arrow key (optional repeat count)",
    "key_up": "Send UP arrow key (optional repeat count)",
    "kill": "Force kill current process (SIGKILL)",
    "shift_tab": "Send SHIFT+TAB key (optional count)",
    "tab": "Send TAB key",
}


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
    AGENT_READY: Literal["agent_ready"] = "agent_ready"  # Fact: agent TUI is stable at input prompt.
    AGENT_READINESS_TIMEOUT: Literal["agent_readiness_timeout"] = (
        "agent_readiness_timeout"  # Fact: agent TUI did not reach ready prompt within timeout.
    )
    AGENT_EVENT: Literal["agent_event"] = "agent_event"  # Agent events (title change, etc.)
    AGENT_ACTIVITY: Literal["agent_activity"] = "agent_activity"  # Agent activity events (tool_use, agent_stop, etc.)
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


@dataclass(frozen=True)
class SystemCommandContext:
    """Context for system commands (no session_id)."""

    command: str = ""
    from_computer: str = "unknown"


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
    available: bool | None
    status: str | None = None
    unavailable_until: str | None = None
    degraded_until: str | None = None
    reason: str | None = None
    error: str | None = None
    model: str | None = None
    model_active: bool | None = None
    model_unavailable_until: str | None = None
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
)
