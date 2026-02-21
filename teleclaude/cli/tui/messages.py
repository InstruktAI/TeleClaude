"""Custom Textual messages for TUI inter-widget communication."""

from __future__ import annotations

from textual.message import Message

from teleclaude.cli.models import (
    AgentAvailabilityInfo,
    ComputerInfo,
    JobInfo,
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
)

# --- Data refresh messages ---


class DataRefreshed(Message):
    """Fired after API refresh completes with new data."""

    def __init__(
        self,
        computers: list[ComputerInfo],
        projects: list[ProjectInfo],
        projects_with_todos: list[ProjectWithTodosInfo],
        sessions: list[SessionInfo],
        availability: dict[str, AgentAvailabilityInfo],
        jobs: list[JobInfo],
        tts_enabled: bool,
        pane_theming_mode: str,
    ) -> None:
        super().__init__()
        self.computers = computers
        self.projects = projects
        self.projects_with_todos = projects_with_todos
        self.sessions = sessions
        self.availability = availability
        self.jobs = jobs
        self.tts_enabled = tts_enabled
        self.pane_theming_mode = pane_theming_mode


# --- Session interaction messages ---


class SessionSelected(Message):
    """User selected a session in the tree (arrow/click)."""

    def __init__(self, session_id: str, source: str = "click") -> None:
        super().__init__()
        self.session_id = session_id
        self.source = source


class PreviewChanged(Message):
    """Preview session changed — PaneBridge should update layout.

    request_focus: If True, transfer tmux focus to the preview pane.
                   Space sets False (preview without focus shift).
                   Enter/click set True (preview AND focus the pane).
    """

    def __init__(self, session_id: str | None, *, request_focus: bool = False) -> None:
        super().__init__()
        self.session_id = session_id
        self.request_focus = request_focus


class StickyChanged(Message):
    """Sticky sessions changed — PaneBridge should update layout."""

    def __init__(self, session_ids: list[str]) -> None:
        super().__init__()
        self.session_ids = session_ids


class FocusPaneRequest(Message):
    """Request to focus a tmux pane for a session."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


class KillSessionRequest(Message):
    """Request to kill a session (after confirmation)."""

    def __init__(self, session_id: str, computer: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.computer = computer


class RestartSessionRequest(Message):
    """Request to restart a session."""

    def __init__(self, session_id: str, computer: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.computer = computer


class ReviveSessionRequest(Message):
    """Request to revive a headless session (create its tmux pane)."""

    def __init__(self, session_id: str, computer: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.computer = computer


class CreateSessionRequest(Message):
    """Request to create a new session."""

    def __init__(
        self,
        computer: str,
        project_path: str,
        agent: str | None = None,
        thinking_mode: str | None = None,
        title: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__()
        self.computer = computer
        self.project_path = project_path
        self.agent = agent
        self.thinking_mode = thinking_mode
        self.title = title
        self.message = message


# --- WebSocket push messages ---


class AgentActivity(Message):
    """Agent activity event from WebSocket."""

    def __init__(
        self,
        session_id: str,
        activity_type: str,
        tool_name: str | None = None,
        tool_preview: str | None = None,
        summary: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.activity_type = activity_type
        self.tool_name = tool_name
        self.tool_preview = tool_preview
        self.summary = summary
        self.timestamp = timestamp


class SessionStarted(Message):
    """Session started event from WebSocket."""

    def __init__(self, session: SessionInfo) -> None:
        super().__init__()
        self.session = session


class SessionUpdated(Message):
    """Session updated event from WebSocket."""

    def __init__(self, session: SessionInfo) -> None:
        super().__init__()
        self.session = session


class SessionClosed(Message):
    """Session closed event from WebSocket."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


# --- Preparation messages ---


class TodoSelected(Message):
    """User selected a todo item."""

    def __init__(self, slug: str) -> None:
        super().__init__()
        self.slug = slug


class DocPreviewRequest(Message):
    """Request to preview a document in a pane."""

    def __init__(self, doc_id: str, command: str, title: str) -> None:
        super().__init__()
        self.doc_id = doc_id
        self.command = command
        self.title = title


class DocEditRequest(Message):
    """Request to edit a document in the editor pane."""

    def __init__(self, doc_id: str, command: str, title: str) -> None:
        super().__init__()
        self.doc_id = doc_id
        self.command = command
        self.title = title


# --- Cursor context messages ---


class CursorContextChanged(Message):
    """Cursor moved to a different item type — ActionBar should update hints."""

    def __init__(self, item_type: str) -> None:
        super().__init__()
        self.item_type = item_type  # "session" | "computer" | "project"


# --- Settings messages ---


class SettingsChanged(Message):
    """Settings were changed (TTS, animation, pane theming)."""

    def __init__(self, key: str, value: object) -> None:
        super().__init__()
        self.key = key
        self.value = value
