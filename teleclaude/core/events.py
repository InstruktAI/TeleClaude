"""Event system for TeleClaude adapter communication.

Provides type-safe event definitions for adapter-daemon communication.
"""

from typing import Literal, Optional

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
    "enter",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "rename",
    "claude",
    "claude_resume",
    "message",
    "voice",
    "file",
    "session_closed",
    "session_reopened",
    "session_deleted",
    "working_dir_changed",
    "system_command",
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
    ENTER: Literal["enter"] = "enter"
    KEY_UP: Literal["key_up"] = "key_up"
    KEY_DOWN: Literal["key_down"] = "key_down"
    KEY_LEFT: Literal["key_left"] = "key_left"
    KEY_RIGHT: Literal["key_right"] = "key_right"

    # Session management
    RENAME: Literal["rename"] = "rename"

    # AI commands
    CLAUDE: Literal["claude"] = "claude"
    CLAUDE_RESUME: Literal["claude_resume"] = "claude_resume"

    # User input
    MESSAGE: Literal["message"] = "message"  # Messages to long-running processes

    # Media and events
    VOICE: Literal["voice"] = "voice"  # Voice message received
    FILE: Literal["file"] = "file"  # File or photo uploaded

    # Session lifecycle events
    SESSION_CLOSED: Literal["session_closed"] = "session_closed"  # Session marked closed in DB
    SESSION_REOPENED: Literal["session_reopened"] = "session_reopened"  # Session reopened
    SESSION_DELETED: Literal["session_deleted"] = "session_deleted"  # Session deleted from DB
    WORKING_DIR_CHANGED: Literal["working_dir_changed"] = "working_dir_changed"  # Working directory updated

    # System commands
    SYSTEM_COMMAND: Literal["system_command"] = "system_command"  # System-level commands (deploy, etc.)


def parse_command_string(command_str: str) -> tuple[Optional[str], list[str]]:
    """Parse command string into event name and arguments.

    Used by adapters that receive raw command strings (e.g., Redis, REST API).
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
    import shlex

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
