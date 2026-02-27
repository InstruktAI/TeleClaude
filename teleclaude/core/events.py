"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Optional, Union, cast

# Event bus carries internal events (not user commands).
EventType = Literal[
    "session_started",
    "session_closed",
    "session_updated",
    "session_status",
    "agent_event",
    "agent_activity",
    "error",
    "system_command",
]

# Agent hook event types (payload event_type values from agents)
AgentHookEventType = Literal[
    "session_start",
    "user_prompt_submit",
    "tool_use",
    "tool_done",
    "agent_stop",
    "session_end",
    "notification",
    "error",
    "before_agent",
    "before_model",
    "before_tool_selection",
    "before_tool",
    "after_tool",
    "pre_compress",
    "pre_tool_use",
    "post_tool_use",
    "post_tool_use_failure",
    "subagent_start",
    "subagent_stop",
    "pre_compact",
]


class AgentHookEvents:
    """Agent hook payload event types (distinct from TeleClaudeEvents commands)."""

    AGENT_SESSION_START: AgentHookEventType = "session_start"
    USER_PROMPT_SUBMIT: AgentHookEventType = "user_prompt_submit"
    TOOL_DONE: AgentHookEventType = "tool_done"
    AGENT_STOP: AgentHookEventType = "agent_stop"
    AGENT_SESSION_END: AgentHookEventType = "session_end"
    AGENT_NOTIFICATION: AgentHookEventType = "notification"
    AGENT_ERROR: AgentHookEventType = "error"

    # Additional hook events (captured for future-proofing, no active handlers yet)
    BEFORE_AGENT: AgentHookEventType = "before_agent"
    BEFORE_MODEL: AgentHookEventType = "before_model"
    TOOL_USE: AgentHookEventType = "tool_use"
    BEFORE_TOOL_SELECTION: AgentHookEventType = "before_tool_selection"
    BEFORE_TOOL: AgentHookEventType = "before_tool"
    AFTER_TOOL: AgentHookEventType = "after_tool"
    PRE_COMPRESS: AgentHookEventType = "pre_compress"
    PRE_TOOL_USE: AgentHookEventType = "pre_tool_use"
    POST_TOOL_USE: AgentHookEventType = "post_tool_use"
    POST_TOOL_USE_FAILURE: AgentHookEventType = "post_tool_use_failure"
    SUBAGENT_START: AgentHookEventType = "subagent_start"
    SUBAGENT_STOP: AgentHookEventType = "subagent_stop"
    PRE_COMPACT: AgentHookEventType = "pre_compact"

    # Internal handlers currently only use:
    # - AGENT_SESSION_START: Initialize headless session, anchor native IDs
    # - USER_PROMPT_SUBMIT: Capture last user input for session history
    # - TOOL_USE: Agent started a tool call (checkpoint timing, TUI activity)
    # - TOOL_DONE: Tool execution completed (activity/control-plane signal)
    # - AGENT_STOP: Trigger turn completion, poll transcript for final model response
    # - AGENT_NOTIFICATION: Notify listeners (tmux) and initiators (remote)
    # Other events are enqueued but have no active logic in the daemon yet.

    # Mapping from agent-specific hook event names to TeleClaude internal event types
    HOOK_EVENT_MAP: Mapping[str, Mapping[str, AgentHookEventType]] = MappingProxyType(
        {
            "claude": MappingProxyType(
                {
                    "SessionStart": AGENT_SESSION_START,
                    "UserPromptSubmit": USER_PROMPT_SUBMIT,
                    "PreToolUse": TOOL_USE,
                    "PermissionRequest": AGENT_NOTIFICATION,
                    "PostToolUse": TOOL_DONE,
                    "PostToolUseFailure": TOOL_DONE,
                    "SubagentStart": TOOL_DONE,
                    "SubagentStop": TOOL_DONE,
                    "Stop": AGENT_STOP,
                    "PreCompact": PRE_COMPACT,
                    "SessionEnd": AGENT_SESSION_END,
                    "Notification": AGENT_NOTIFICATION,
                }
            ),
            "gemini": MappingProxyType(
                {
                    "SessionStart": AGENT_SESSION_START,
                    "BeforeAgent": USER_PROMPT_SUBMIT,
                    "AfterAgent": AGENT_STOP,
                    "BeforeModel": BEFORE_MODEL,
                    "AfterModel": TOOL_USE,
                    "BeforeToolSelection": BEFORE_TOOL_SELECTION,
                    "BeforeTool": BEFORE_TOOL,
                    "AfterTool": TOOL_DONE,
                    "PreCompress": PRE_COMPRESS,
                    "Notification": AGENT_NOTIFICATION,
                    "SessionEnd": AGENT_SESSION_END,
                }
            ),
            "codex": MappingProxyType(
                {
                    # Codex only supports a single notify hook (agent-turn-complete)
                    "agent-turn-complete": AGENT_STOP,
                }
            ),
        }
    )

    ALL: set[AgentHookEventType] = cast(
        "set[AgentHookEventType]",
        {v for agent_map in HOOK_EVENT_MAP.values() for v in agent_map.values()} | {AGENT_ERROR},
    )
    RECEIVER_HANDLED: frozenset[AgentHookEventType] = frozenset(
        {
            AGENT_SESSION_START,
            USER_PROMPT_SUBMIT,
            TOOL_DONE,
            TOOL_USE,
            AGENT_STOP,
            AGENT_NOTIFICATION,
            AGENT_ERROR,
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


@dataclass(frozen=True)
class AgentNotificationPayload:
    """Internal payload for agent notification hook.

    guard: loose-dict - Agent hook data varies by agent.
    """

    message: str = ""
    raw: Mapping[str, object] = field(default_factory=dict)
    session_id: str | None = None
    transcript_path: str | None = None
    source_computer: str | None = None


@dataclass(frozen=True)
class AgentSessionEndPayload:
    """Internal payload for agent session_end hook.

    guard: loose-dict - Agent hook data varies by agent.
    """

    session_id: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


AgentEventPayload = Union[
    AgentSessionStartPayload,
    UserPromptSubmitPayload,
    AgentOutputPayload,
    AgentStopPayload,
    AgentNotificationPayload,
    AgentSessionEndPayload,
]


# Event types supported by build_agent_payload
# Additional AgentHookEventType values exist but have no payload builders yet
SUPPORTED_PAYLOAD_TYPES: set[AgentHookEventType] = {
    AgentHookEvents.AGENT_SESSION_START,
    AgentHookEvents.USER_PROMPT_SUBMIT,
    AgentHookEvents.TOOL_DONE,
    AgentHookEvents.AGENT_STOP,
    AgentHookEvents.AGENT_NOTIFICATION,
    AgentHookEvents.AGENT_SESSION_END,
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

    if event_type == AgentHookEvents.TOOL_DONE:
        return AgentOutputPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    if event_type == AgentHookEvents.AGENT_STOP:
        return AgentStopPayload(
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            prompt=cast(str | None, data.get("prompt")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    if event_type == AgentHookEvents.AGENT_NOTIFICATION:
        return AgentNotificationPayload(
            message=cast(str, data.get("message", "")),
            session_id=native_id,
            transcript_path=cast(str | None, data.get("transcript_path")),
            source_computer=cast(str | None, data.get("source_computer")),
            raw=frozen_raw,
        )

    if event_type == AgentHookEvents.AGENT_SESSION_END:
        return AgentSessionEndPayload(
            session_id=native_id,
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
# pylint: disable=invalid-name  # UiCommands is a module-level mapping, not a constant
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
    "new_session": "Create a new tmux session",
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
    SESSION_CLOSED: Literal["session_closed"] = "session_closed"
    SESSION_UPDATED: Literal["session_updated"] = "session_updated"  # Session fields updated in DB
    SESSION_STATUS: Literal["session_status"] = "session_status"  # Canonical lifecycle status transition
    AGENT_EVENT: Literal["agent_event"] = "agent_event"  # Agent events (title change, etc.)
    AGENT_ACTIVITY: Literal["agent_activity"] = "agent_activity"  # Agent activity events (tool_use, tool_done, etc.)
    ERROR: Literal["error"] = "error"


ErrorSeverity = Literal["warning", "error", "critical"]


def parse_command_string(command_str: str) -> tuple[Optional[str], list[str]]:
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
    caption: Optional[str] = None
    file_size: int = 0


@dataclass(frozen=True)
class VoiceEventContext:
    """Context for voice message events."""

    session_id: str
    file_path: str = ""
    duration: Optional[float] = None
    message_id: Optional[str] = None
    message_thread_id: Optional[int] = None
    origin: Optional[str] = None


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
      status: Canonical lifecycle status value (accepted, awaiting_output,
              active_output, stalled, completed, error, closed).
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
class AgentActivityEvent:
    """Agent activity event for real-time UI updates.

    Direct event from coordinator to consumers (TUI/Web) without DB mediation.
    Carries typed activity events (tool_use, tool_done, agent_stop) with optional metadata.

    Canonical contract fields (ucap-canonical-contract):
      canonical_type: stable outbound vocabulary type (user_prompt_submit,
                      agent_output_update, agent_output_stop).
      message_intent: routing intent for this event (ctrl_activity).
      delivery_scope:  routing scope (CTRL for all activity events).
    """

    session_id: str
    event_type: AgentHookEventType
    tool_name: str | None = None
    tool_preview: str | None = None
    summary: str | None = None
    timestamp: str | None = None
    # Canonical contract fields (preserved as optional for backward compatibility)
    canonical_type: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


@dataclass(frozen=True)
class ErrorEventContext:
    """Context for error events.

    guard: loose-dict - Error detail data varies by error.
    """

    session_id: str | None
    message: str
    source: Optional[str] = None
    details: Optional[Mapping[str, object]] = None
    severity: ErrorSeverity = "error"
    retryable: bool = False
    code: Optional[str] = None


# Union of all event context types (for adapter_client handler signatures)
EventContext = (
    MessageEventContext
    | SessionLifecycleContext
    | SystemCommandContext
    | AgentEventContext
    | ErrorEventContext
    | SessionUpdatedContext
    | SessionStatusContext
    | AgentActivityEvent
)
