"""Custom Textual messages for TUI inter-widget communication."""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class _ChiptunesPendingCommand:
    command_id: str = ""
    action: str = ""


@dataclass(frozen=True)
class _ChiptunesState:
    loaded: bool = False
    playback: str = "cold"
    state_version: int = 0
    playing: bool = False
    track: str = ""
    sid_path: str = ""
    pending: _ChiptunesPendingCommand = field(default_factory=_ChiptunesPendingCommand)


@dataclass(frozen=True)
class _RefreshPayload:
    computers: list[ComputerInfo]
    projects: list[ProjectInfo]
    projects_with_todos: list[ProjectWithTodosInfo]
    sessions: list[SessionInfo]
    availability: dict[str, AgentAvailabilityInfo]
    jobs: list[JobInfo]
    tts_enabled: bool


class DataRefreshed(Message):
    """Fired after API refresh completes with new data."""

    def __init__(self, *payload: object, **chiptunes_state: object) -> None:
        super().__init__()
        if len(payload) != 7:
            raise TypeError("DataRefreshed expects 7 positional payload values")
        self._payload = _RefreshPayload(*payload)
        self._chiptunes = self._build_chiptunes_state(chiptunes_state)

    @staticmethod
    def _build_chiptunes_state(chiptunes_state: dict[str, object]) -> _ChiptunesState:
        """Normalize optional chiptunes fields into an immutable payload."""
        expected = {
            "chiptunes_loaded": "loaded",
            "chiptunes_playback": "playback",
            "chiptunes_state_version": "state_version",
            "chiptunes_playing": "playing",
            "chiptunes_track": "track",
            "chiptunes_sid_path": "sid_path",
            "chiptunes_pending_command_id": "pending_command_id",
            "chiptunes_pending_action": "pending_action",
        }
        unknown = set(chiptunes_state) - set(expected)
        if unknown:
            unknown_names = ", ".join(sorted(unknown))
            raise TypeError(f"Unexpected chiptunes fields: {unknown_names}")
        normalized = {
            target: chiptunes_state[source] for source, target in expected.items() if source in chiptunes_state
        }
        pending = _ChiptunesPendingCommand(
            command_id=str(normalized.pop("pending_command_id", "")),
            action=str(normalized.pop("pending_action", "")),
        )
        return _ChiptunesState(**normalized, pending=pending)

    @property
    def computers(self) -> list[ComputerInfo]:
        """Return the refreshed computer list."""
        return self._payload.computers

    @property
    def projects(self) -> list[ProjectInfo]:
        """Return the refreshed project list."""
        return self._payload.projects

    @property
    def projects_with_todos(self) -> list[ProjectWithTodosInfo]:
        """Return projects enriched with todo metadata."""
        return self._payload.projects_with_todos

    @property
    def sessions(self) -> list[SessionInfo]:
        """Return the refreshed session list."""
        return self._payload.sessions

    @property
    def availability(self) -> dict[str, AgentAvailabilityInfo]:
        """Return agent availability keyed by identifier."""
        return self._payload.availability

    @property
    def jobs(self) -> list[JobInfo]:
        """Return the refreshed job list."""
        return self._payload.jobs

    @property
    def tts_enabled(self) -> bool:
        """Return whether TTS is enabled."""
        return self._payload.tts_enabled

    @property
    def chiptunes_loaded(self) -> bool:
        """Return whether chiptunes assets are loaded."""
        return self._chiptunes.loaded

    @property
    def chiptunes_playback(self) -> str:
        """Return the current chiptunes playback mode."""
        return self._chiptunes.playback

    @property
    def chiptunes_state_version(self) -> int:
        """Return the chiptunes state version counter."""
        return self._chiptunes.state_version

    @property
    def chiptunes_playing(self) -> bool:
        """Return whether chiptunes audio is currently playing."""
        return self._chiptunes.playing

    @property
    def chiptunes_track(self) -> str:
        """Return the current chiptunes track name."""
        return self._chiptunes.track

    @property
    def chiptunes_sid_path(self) -> str:
        """Return the path to the current SID file."""
        return self._chiptunes.sid_path

    @property
    def chiptunes_pending_command_id(self) -> str:
        """Return the pending chiptunes command identifier."""
        return self._chiptunes.pending.command_id

    @property
    def chiptunes_pending_action(self) -> str:
        """Return the pending chiptunes action name."""
        return self._chiptunes.pending.action


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


class RestartSessionsRequest(Message):
    """Request to restart multiple sessions on a computer."""

    def __init__(self, computer: str, session_ids: list[str]) -> None:
        super().__init__()
        self.computer = computer
        self.session_ids = session_ids


class ReviveSessionRequest(Message):
    """Request to revive a headless session (create its tmux pane)."""

    def __init__(self, session_id: str, computer: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.computer = computer


class CreateSessionRequest(Message):
    """Request to create a new session.

    When revive_session_id is set, the session is revived by TeleClaude session ID
    (agent is resolved from the session record).
    When native_session_id is set, agent_resume is used with the selected agent.
    """

    def __init__(self, computer: str, project_path: str, **options: object) -> None:
        super().__init__()
        expected = {
            "agent",
            "thinking_mode",
            "title",
            "message",
            "revive_session_id",
            "native_session_id",
        }
        unknown = set(options) - expected
        if unknown:
            unknown_names = ", ".join(sorted(unknown))
            raise TypeError(f"Unexpected create-session fields: {unknown_names}")
        self._request = {
            "computer": computer,
            "project_path": project_path,
            "agent": options.get("agent"),
            "thinking_mode": options.get("thinking_mode"),
            "title": options.get("title"),
            "message": options.get("message"),
            "revive_session_id": options.get("revive_session_id"),
            "native_session_id": options.get("native_session_id"),
        }

    @property
    def computer(self) -> str:
        """Return the target computer name."""
        return str(self._request["computer"])

    @property
    def project_path(self) -> str:
        """Return the project path for the session request."""
        return str(self._request["project_path"])

    @property
    def agent(self) -> str | None:
        """Return the requested agent when provided."""
        return self._request["agent"] if isinstance(self._request["agent"], str) else None

    @property
    def thinking_mode(self) -> str | None:
        """Return the requested thinking mode when provided."""
        return self._request["thinking_mode"] if isinstance(self._request["thinking_mode"], str) else None

    @property
    def title(self) -> str | None:
        """Return the requested session title when provided."""
        return self._request["title"] if isinstance(self._request["title"], str) else None

    @property
    def message(self) -> str | None:
        """Return the initial session message when provided."""
        return self._request["message"] if isinstance(self._request["message"], str) else None

    @property
    def revive_session_id(self) -> str | None:
        """Return the TeleClaude session ID to revive when provided."""
        value = self._request["revive_session_id"]
        return value if isinstance(value, str) else None

    @property
    def native_session_id(self) -> str | None:
        """Return the native session ID to resume when provided."""
        value = self._request["native_session_id"]
        return value if isinstance(value, str) else None


# --- WebSocket push messages ---


class AgentActivity(Message):
    """Agent activity event from WebSocket."""

    def __init__(self, session_id: str, activity_type: str, **details: object) -> None:
        super().__init__()
        expected = {"canonical_type", "tool_name", "tool_preview", "summary", "timestamp"}
        unknown = set(details) - expected
        if unknown:
            unknown_names = ", ".join(sorted(unknown))
            raise TypeError(f"Unexpected agent activity fields: {unknown_names}")
        self._event = {
            "session_id": session_id,
            "activity_type": activity_type,
            "canonical_type": details.get("canonical_type"),
            "tool_name": details.get("tool_name"),
            "tool_preview": details.get("tool_preview"),
            "summary": details.get("summary"),
            "timestamp": details.get("timestamp"),
        }

    @property
    def session_id(self) -> str:
        """Return the session identifier for this activity event."""
        return str(self._event["session_id"])

    @property
    def activity_type(self) -> str:
        """Return the raw activity type from the event stream."""
        return str(self._event["activity_type"])

    @property
    def canonical_type(self) -> str | None:
        """Return the normalized activity type when available."""
        value = self._event["canonical_type"]
        return value if isinstance(value, str) else None

    @property
    def tool_name(self) -> str | None:
        """Return the tool name for tool-related events."""
        value = self._event["tool_name"]
        return value if isinstance(value, str) else None

    @property
    def tool_preview(self) -> str | None:
        """Return the tool preview text when supplied."""
        value = self._event["tool_preview"]
        return value if isinstance(value, str) else None

    @property
    def summary(self) -> str | None:
        """Return the agent stop summary when present."""
        value = self._event["summary"]
        return value if isinstance(value, str) else None

    @property
    def timestamp(self) -> str | None:
        """Return the event timestamp when present."""
        value = self._event["timestamp"]
        return value if isinstance(value, str) else None


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


# --- Settings messages ---


class StateChanged(Message):
    """State changed and should be persisted to disk."""


class SettingsChanged(Message):
    """Settings were changed (TTS, animation, pane theming)."""

    def __init__(self, key: str, value: object) -> None:
        super().__init__()
        self.key = key
        self.value = value
