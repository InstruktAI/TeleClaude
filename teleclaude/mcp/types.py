"""TypedDict definitions and exceptions for MCP tools."""

from datetime import datetime
from typing import NotRequired, TypedDict

from teleclaude.types import SystemStats


class RemoteRequestError(Exception):
    """Error from remote request (timeout, JSON error, or remote error response)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ComputerInfo(TypedDict):
    """Computer information returned by list_computers."""

    name: str
    status: str
    last_seen: datetime
    user: str | None
    host: str | None
    role: str | None
    system_stats: SystemStats | None
    tmux_binary: NotRequired[str | None]


class SessionInfo(TypedDict):
    """Session information returned by list_sessions."""

    session_id: str
    origin_adapter: str
    title: str
    project_path: str | None
    subdir: str | None
    status: str
    created_at: str
    last_activity: str
    computer: str


class SessionDataResult(TypedDict, total=False):
    """Result from get_session_data."""

    status: str  # Required - always present
    session_id: str
    transcript: str | None
    last_activity: str | None
    project_path: str | None
    subdir: str | None
    error: str  # Present in error responses
    effective_tail_chars: int  # Present in success responses
    cap_notice: str  # Present when transcript is capped
    captured_at: str  # Timestamp when data was captured
    max_chars: int  # Max chars for response
    requested_tail_chars: int  # Requested tail chars
    messages: str  # Message transcript
    truncated: bool  # Whether messages were truncated


class StartSessionResult(TypedDict, total=False):
    """Result from start_session."""

    status: str  # Required - always present
    session_id: str
    tmux_session_name: str | None
    message: str | None


class SendMessageResult(TypedDict, total=False):
    """Result from send_message."""

    status: str  # Required - always present
    message: str | None


class SendResultResult(TypedDict, total=False):
    """Result from send_result."""

    status: str  # Required - always present
    message: str | None  # Error message
    message_id: str | None  # Success case
    warning: str | None  # Warning message


class RunAgentCommandResult(TypedDict, total=False):
    """Result from run_agent_command."""

    status: str  # Required - always present
    session_id: str
    tmux_session_name: str | None
    message: str | None


class DeployComputerResult(TypedDict):
    """Deployment result for a single computer."""

    status: str
    message: str | None


class EndSessionResult(TypedDict):
    """Result from end_session."""

    status: str
    message: str


class StopNotificationsResult(TypedDict):
    """Result from stop_notifications."""

    status: str
    message: str


class NextPrepareResult(TypedDict):
    """Result from next_prepare."""

    status: str
    message: str


class NextWorkResult(TypedDict):
    """Result from next_work."""

    status: str
    message: str


class MarkPhaseResult(TypedDict):
    """Result from mark_phase."""

    status: str
    message: str


class MCPHealthSnapshot(TypedDict):
    """Snapshot of MCP server health state."""

    server_present: bool
    is_serving: bool
    socket_exists: bool
    active_connections: int
    last_accept_age_s: float | None
