"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

from typing import Literal

# Type alias for valid event names - provides compile-time type checking
EventType = Literal[
    "new_session",
    "list_sessions",
    "list_projects",
    "cd",
    "kill",
    "cancel",
    "cancel2x",
    "escape",
    "escape2x",
    "ctrl",
    "tab",
    "shift_tab",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "rename",
    "claude",
    "claude-resume",
    "message",
    "voice",
    "topic_closed",
]


class TeleClaudeEvents:
    """Standard TeleClaude events that daemon handles.

    These events are emitted by adapters and handled by the daemon.
    Adapter-specific events (like 'resize', 'help') are NOT included here.
    """

    # Session lifecycle
    NEW_SESSION: Literal["new_session"] = "new_session"
    LIST_SESSIONS: Literal["list_sessions"] = "list_sessions"

    # Project management
    LIST_PROJECTS: Literal["list_projects"] = "list_projects"
    CD: Literal["cd"] = "cd"

    # Process control
    KILL: Literal["kill"] = "kill"
    CANCEL: Literal["cancel"] = "cancel"
    CANCEL_2X: Literal["cancel2x"] = "cancel2x"

    # Terminal control
    ESCAPE: Literal["escape"] = "escape"
    ESCAPE_2X: Literal["escape2x"] = "escape2x"
    CTRL: Literal["ctrl"] = "ctrl"
    TAB: Literal["tab"] = "tab"
    SHIFT_TAB: Literal["shift_tab"] = "shift_tab"
    KEY_UP: Literal["key_up"] = "key_up"
    KEY_DOWN: Literal["key_down"] = "key_down"
    KEY_LEFT: Literal["key_left"] = "key_left"
    KEY_RIGHT: Literal["key_right"] = "key_right"

    # Session management
    RENAME: Literal["rename"] = "rename"

    # AI commands
    CLAUDE: Literal["claude"] = "claude"
    CLAUDE_RESUME: Literal["claude-resume"] = "claude-resume"

    # User input
    MESSAGE: Literal["message"] = "message"  # Messages to long-running processes

    # Media and events
    VOICE: Literal["voice"] = "voice"  # Voice message received
    TOPIC_CLOSED: Literal["topic_closed"] = "topic_closed"  # Telegram topic closed/deleted
