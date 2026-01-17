"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional, Union

if TYPE_CHECKING:
    from teleclaude.core.models import SessionLaunchIntent

# Type alias for valid event names - provides compile-time type checking
EventType = Literal[
    "new_session",
    "create_session",
    "list_sessions",
    "get_session_data",
    "list_projects",
    "list_projects_with_todos",
    "list_todos",
    "get_computer_info",
    "cd",
    "kill",
    "cancel",
    "cancel2x",
    "escape",
    "escape2x",
    "ctrl",
    "tab",
    "shift_tab",
    "backspace",
    "enter",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "rename",
    "agent",
    "agent_restart",
    "agent_resume",
    "message",
    "voice",
    "file",
    "session_created",
    "session_removed",
    "system_command",
    "agent_event",
    "error",
    "session_updated",
]

# Command events that use CommandEventContext (type alias for static typing).
CommandEventType = Literal[
    "new_session",
    "list_sessions",
    "get_session_data",
    "list_projects",
    "list_projects_with_todos",
    "list_todos",
    "get_computer_info",
    "cd",
    "kill",
    "cancel",
    "cancel2x",
    "escape",
    "escape2x",
    "ctrl",
    "tab",
    "shift_tab",
    "backspace",
    "enter",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "rename",
    "agent",
    "agent_restart",
    "agent_resume",
]

# Agent hook event types (payload event_type values from agents)
AgentHookEventType = Literal["session_start", "prompt", "stop", "session_end", "notification", "error"]


class AgentHookEvents:
    """Agent hook payload event types (distinct from TeleClaudeEvents commands)."""

    AGENT_SESSION_START: AgentHookEventType = "session_start"
    AGENT_PROMPT: AgentHookEventType = "prompt"
    AGENT_STOP: AgentHookEventType = "stop"
    AGENT_SESSION_END: AgentHookEventType = "session_end"
    AGENT_NOTIFICATION: AgentHookEventType = "notification"
    AGENT_ERROR: AgentHookEventType = "error"
    ALL: set[AgentHookEventType] = {
        AGENT_SESSION_START,
        AGENT_PROMPT,
        AGENT_STOP,
        AGENT_SESSION_END,
        AGENT_NOTIFICATION,
        AGENT_ERROR,
    }


@dataclass
class AgentSessionStartPayload:
    """Internal payload for agent session_start hook."""

    raw: dict[str, object] = field(default_factory=dict)  # noqa: loose-dict - Agent hook data varies by agent
    transcript_path: str | None = None
    session_id: str | None = None


@dataclass
class AgentPromptPayload:
    """Internal payload for agent prompt hook (turn started)."""

    prompt: str
    session_id: str | None = None
    transcript_path: str | None = None
    raw: dict[str, object] = field(default_factory=dict)  # noqa: loose-dict - Agent hook data varies by agent
    source_computer: str | None = None


@dataclass
class AgentStopPayload:
    """Internal payload for agent stop hook."""

    session_id: str | None = None
    transcript_path: str | None = None
    prompt: str | None = None
    raw: dict[str, object] = field(default_factory=dict)  # noqa: loose-dict - Agent hook data varies by agent
    summary: str | None = None
    title: str | None = None
    source_computer: str | None = None


@dataclass
class AgentNotificationPayload:
    """Internal payload for agent notification hook."""

    message: str = ""
    raw: dict[str, object] = field(default_factory=dict)  # noqa: loose-dict - Agent hook data varies by agent
    session_id: str | None = None
    transcript_path: str | None = None
    source_computer: str | None = None


@dataclass
class AgentSessionEndPayload:
    """Internal payload for agent session_end hook."""

    session_id: str | None = None
    raw: dict[str, object] = field(default_factory=dict)  # noqa: loose-dict - Agent hook data varies by agent


AgentEventPayload = Union[
    AgentSessionStartPayload,
    AgentPromptPayload,
    AgentStopPayload,
    AgentNotificationPayload,
    AgentSessionEndPayload,
]


# UI commands mapping (intentionally lowercase - not a constant despite dict type)
# pylint: disable=invalid-name  # UiCommands is a module-level mapping, not a constant
UiCommands = {
    "cd": "Change directory or list trusted directories",
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
    "rename": "Rename current session",
    "resize": "Resize tmux window",
    "shift_tab": "Send SHIFT+TAB key (optional count)",
    "tab": "Send TAB key",
}


class TeleClaudeEvents:
    """Standard TeleClaude events that daemon handles.

    These events are emitted by adapters and handled by the daemon.
    Adapter-specific events (like 'resize', 'help') are NOT included here.
    """

    # Session lifecycle
    NEW_SESSION: Literal["new_session"] = "new_session"
    CREATE_SESSION: Literal["create_session"] = "create_session"
    LIST_SESSIONS: Literal["list_sessions"] = "list_sessions"
    GET_SESSION_DATA: Literal["get_session_data"] = "get_session_data"
    SESSION_CREATED: Literal["session_created"] = "session_created"
    SESSION_REMOVED: Literal["session_removed"] = "session_removed"

    # Project management
    LIST_PROJECTS: Literal["list_projects"] = "list_projects"
    LIST_PROJECTS_WITH_TODOS: Literal["list_projects_with_todos"] = "list_projects_with_todos"
    LIST_TODOS: Literal["list_todos"] = "list_todos"
    GET_COMPUTER_INFO: Literal["get_computer_info"] = "get_computer_info"
    CD: Literal["cd"] = "cd"

    # Process control
    KILL: Literal["kill"] = "kill"
    CANCEL: Literal["cancel"] = "cancel"
    CANCEL_2X: Literal["cancel2x"] = "cancel2x"

    # Tmux control
    ESCAPE: Literal["escape"] = "escape"
    ESCAPE_2X: Literal["escape2x"] = "escape2x"
    CTRL: Literal["ctrl"] = "ctrl"
    TAB: Literal["tab"] = "tab"
    SHIFT_TAB: Literal["shift_tab"] = "shift_tab"
    BACKSPACE: Literal["backspace"] = "backspace"
    ENTER: Literal["enter"] = "enter"
    KEY_UP: Literal["key_up"] = "key_up"
    KEY_DOWN: Literal["key_down"] = "key_down"
    KEY_LEFT: Literal["key_left"] = "key_left"
    KEY_RIGHT: Literal["key_right"] = "key_right"

    # Session management
    RENAME: Literal["rename"] = "rename"
    AGENT_RESTART: Literal["agent_restart"] = "agent_restart"

    # AI commands
    AGENT_START: Literal["agent"] = "agent"
    AGENT_APIART: Literal["agent_restart"] = "agent_restart"
    AGENT_RESUME: Literal["agent_resume"] = "agent_resume"

    # User input
    MESSAGE: Literal["message"] = "message"  # Messages to long-running processes

    # Media and events
    VOICE: Literal["voice"] = "voice"  # Voice message received
    FILE: Literal["file"] = "file"  # File or photo uploaded

    # System commands
    SYSTEM_COMMAND: Literal["system_command"] = "system_command"  # System-level commands (deploy, etc.)

    # Agent events (from hooks)
    AGENT_EVENT: Literal["agent_event"] = "agent_event"  # Agent events (title change, etc.)

    # Error events (from hooks or internal validation)
    ERROR: Literal["error"] = "error"

    # Internal events
    SESSION_UPDATED: Literal["session_updated"] = "session_updated"  # Session fields updated in DB


def parse_command_string(command_str: str) -> tuple[Optional[str], list[str]]:
    """Parse command string into event name and arguments.

    Used by adapters that receive raw command strings (e.g., Redis, API API).
    Telegram adapter doesn't need this - python-telegram-bot parses for us.

    Args:
        command_str: Raw command string (e.g., "/cd /path" or "cd /path")

    Returns:
        Tuple of (event_name, args_list)
        Returns (None, []) if command is empty

    Examples:
        >>> parse_command_string("/cd /home/user")
        ("cd", ["/home/user"])
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


@dataclass
class MessageEventContext:
    """Context for message events."""

    session_id: str
    text: str = ""


@dataclass
class FileEventContext:
    """Context for file upload events."""

    session_id: str
    file_path: str = ""
    filename: str = ""
    caption: Optional[str] = None
    file_size: int = 0


@dataclass
class VoiceEventContext:
    """Context for voice message events."""

    session_id: str
    file_path: str = ""
    duration: Optional[float] = None
    message_id: Optional[str] = None
    message_thread_id: Optional[int] = None
    adapter_type: Optional[str] = None


@dataclass
class SessionLifecycleContext:
    """Context for session lifecycle events."""

    session_id: str


@dataclass
class DeployArgs:
    """Arguments for deploy system command."""

    verify_health: bool = True


@dataclass
class SystemCommandContext:
    """Context for system commands (no session_id)."""

    command: str = ""
    from_computer: str = "unknown"
    args: DeployArgs = field(default_factory=DeployArgs)


@dataclass
class CommandEventContext:  # pylint: disable=too-many-instance-attributes  # Event context requires many metadata fields
    """Context for command events (new_session, cd, kill, etc.)."""

    session_id: str
    args: list[str] = field(default_factory=list)
    # Metadata fields
    adapter_type: Optional[str] = None
    message_thread_id: Optional[int] = None
    title: Optional[str] = None
    project_path: Optional[str] = None
    channel_metadata: Optional[dict[str, object]] = None  # noqa: loose-dict - Adapter communication metadata
    auto_command: Optional[str] = None  # Legacy adapter boundary (deprecated)
    launch_intent: Optional["SessionLaunchIntent"] = None


@dataclass
class AgentEventContext:
    """Context for Agent events (from hooks)."""

    session_id: str
    data: AgentEventPayload
    event_type: AgentHookEventType


@dataclass
class SessionUpdatedContext:
    """Context for session_updated events."""

    session_id: str
    updated_fields: dict[str, object]  # noqa: loose-dict - Dynamic session field updates


@dataclass
class ErrorEventContext:
    """Context for error events."""

    session_id: str
    message: str
    source: Optional[str] = None
    details: Optional[dict[str, object]] = None  # noqa: loose-dict - Error detail data varies by error


# Union of all event context types (for adapter_client handler signatures)
EventContext = (
    CommandEventContext
    | MessageEventContext
    | VoiceEventContext
    | FileEventContext
    | SessionLifecycleContext
    | SystemCommandContext
    | AgentEventContext
    | ErrorEventContext
    | SessionUpdatedContext
)

# Command events that use CommandEventContext and route through _handle_command_event
# Note: agent_event and session_updated are NOT included - they have their own contexts
# and handlers in ui_adapter.py
COMMAND_EVENTS: set[EventType] = {
    "new_session",
    "list_sessions",
    "get_session_data",
    "list_projects",
    "list_projects_with_todos",
    "list_todos",
    "get_computer_info",
    "cd",
    "kill",
    "cancel",
    "cancel2x",
    "escape",
    "escape2x",
    "ctrl",
    "tab",
    "shift_tab",
    "backspace",
    "enter",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "rename",
    "agent",
    "agent_restart",
    "agent_resume",
}
