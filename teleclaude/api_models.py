"""API request/response models for API server."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from teleclaude.core.models import SessionSnapshot


class CreateSessionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to create a new session."""

    model_config = ConfigDict(frozen=True)

    computer: str = Field(..., min_length=2)
    project_path: str = Field(..., min_length=2)
    launch_kind: Literal["empty", "agent", "agent_then_message", "agent_resume"] = "agent"
    agent: Literal["claude", "gemini", "codex"] | None = None
    thinking_mode: Literal["fast", "med", "slow"] | None = None
    title: str | None = None
    message: str | None = None
    auto_command: str | None = None
    native_session_id: str | None = None
    subdir: str | None = None
    human_email: str | None = None
    human_role: Literal["admin", "member", "contributor", "newcomer"] | None = None
    metadata: dict[str, object] | None = None  # guard: loose-dict


class CreateSessionResponseDTO(BaseModel):  # type: ignore[explicit-any]
    """Response from session creation."""

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error"]
    session_id: str
    tmux_session_name: str
    agent: Literal["claude", "gemini", "codex"] | None = None
    error: str | None = None


class SendMessageRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a message to a session."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(..., min_length=1)


class KeysRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a key command to a session."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(..., min_length=1)
    count: int | None = Field(default=None, ge=1)


class VoiceInputRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a voice input to a session."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., min_length=1)
    duration: float | None = None
    message_id: str | None = None
    message_thread_id: int | None = None


class FileUploadRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a file input to a session."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    caption: str | None = None
    file_size: int = 0


class SessionDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for session data in API responses."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    last_input_origin: str | None = None
    title: str
    project_path: str | None = None
    subdir: str | None = None
    thinking_mode: str | None = None
    active_agent: str | None = None
    status: str
    created_at: str | None = None
    last_activity: str | None = None
    last_input: str | None = None
    last_input_at: str | None = None
    last_output_summary: str | None = None
    last_output_summary_at: str | None = None
    last_output_digest: str | None = None
    native_session_id: str | None = None
    tmux_session_name: str | None = None
    initiator_session_id: str | None = None
    computer: str | None = None
    human_email: str | None = None
    human_role: str | None = None
    visibility: str = "private"
    session_metadata: dict[str, object] | None = None  # guard: loose-dict

    @classmethod
    def from_core(cls, session: "SessionSnapshot", computer: str | None = None) -> "SessionDTO":
        """Map from core SessionSnapshot dataclass."""
        return cls(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            thinking_mode=session.thinking_mode,
            active_agent=session.active_agent,
            status=session.status,
            created_at=session.created_at,
            last_activity=session.last_activity,
            last_input=session.last_input,
            last_input_at=session.last_input_at,
            last_output_summary=session.last_output_summary,
            last_output_summary_at=session.last_output_summary_at,
            last_output_digest=session.last_output_digest,
            native_session_id=session.native_session_id,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
            computer=computer,
            human_email=session.human_email,
            human_role=session.human_role,
            visibility=session.visibility or "private",
            session_metadata=session.session_metadata,
        )


class PersonDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for person info (safe subset — no credentials)."""

    model_config = ConfigDict(frozen=True)

    name: str
    email: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"


class ComputerDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for computer info."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    user: str | None = None
    host: str | None = None
    is_local: bool
    tmux_binary: str | None = None


class ProjectDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for project info."""

    model_config = ConfigDict(frozen=True)

    computer: str
    name: str
    path: str
    description: str | None = None


class TodoDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for todo info."""

    model_config = ConfigDict(frozen=True)

    slug: str
    status: str
    description: str | None = None
    computer: str | None = None
    project_path: str | None = None
    has_requirements: bool
    has_impl_plan: bool
    build_status: str | None = None
    review_status: str | None = None
    dor_score: int | None = None
    deferrals_status: str | None = None
    findings_count: int = 0
    files: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)
    group: str | None = None


class ProjectWithTodosDTO(ProjectDTO):  # type: ignore[explicit-any]
    """DTO for project with its todos."""

    model_config = ConfigDict(frozen=True)

    todos: list[TodoDTO] = Field(default_factory=list)


class AgentAvailabilityDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for agent availability."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["claude", "gemini", "codex"]
    available: bool | None
    status: Literal["available", "unavailable", "degraded"] | None = None
    unavailable_until: str | None = None
    reason: str | None = None
    error: str | None = None


# WebSocket Event DTOs


class SessionsInitialDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for sessions_initial event."""

    model_config = ConfigDict(frozen=True)

    sessions: list[SessionDTO]
    computer: str | None = None


class SessionsInitialEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for initial sessions list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["sessions_initial"] = "sessions_initial"
    data: SessionsInitialDataDTO


class ProjectsInitialDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for projects_initial event."""

    model_config = ConfigDict(frozen=True)

    projects: list[ProjectWithTodosDTO | ProjectDTO]
    computer: str | None = None


class ProjectsInitialEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for initial projects list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["projects_initial", "preparation_initial"]
    data: ProjectsInitialDataDTO


class SessionStartedEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for session creation."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_started"]
    data: SessionDTO


class SessionUpdatedEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for session updates."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_updated"]
    data: SessionDTO


class SessionClosedDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for session_closed event."""

    model_config = ConfigDict(frozen=True)

    session_id: str


class SessionClosedEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for session closure."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_closed"] = "session_closed"
    data: SessionClosedDataDTO


class RefreshDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for refresh events."""

    model_config = ConfigDict(frozen=True)

    computer: str | None = None
    project_path: str | None = None


class RefreshEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for generic refreshes."""

    model_config = ConfigDict(frozen=True)

    event: Literal[
        "computer_updated",
        "project_updated",
        "projects_updated",
        "todos_updated",
        "todo_created",
        "todo_updated",
        "todo_removed",
    ]
    data: RefreshDataDTO


class ErrorEventDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for error events."""

    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    message: str
    source: str | None = None
    details: dict[str, object] | None = None  # guard: loose-dict - error details vary
    severity: Literal["warning", "error", "critical"] = "error"
    retryable: bool = False
    code: str | None = None


class ErrorEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for errors."""

    model_config = ConfigDict(frozen=True)

    event: Literal["error"] = "error"
    data: ErrorEventDataDTO


class AgentActivityEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for agent activity (tool_use, tool_done, agent_stop)."""

    model_config = ConfigDict(frozen=True)

    event: Literal["agent_activity"] = "agent_activity"
    session_id: str
    type: str
    tool_name: str | None = None
    tool_preview: str | None = None
    summary: str | None = None
    timestamp: str | None = None


class TTSSettingsDTO(BaseModel):  # type: ignore[explicit-any]
    """TTS section of settings response."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False


PaneThemingMode = Literal["off", "highlight", "highlight2", "agent", "agent_plus", "full", "semi"]


class SettingsDTO(BaseModel):  # type: ignore[explicit-any]
    """Runtime settings response."""

    model_config = ConfigDict(frozen=True)

    tts: TTSSettingsDTO
    pane_theming_mode: PaneThemingMode = "full"


class TTSSettingsPatchDTO(BaseModel):  # type: ignore[explicit-any]
    """TTS section of settings patch request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool | None = None


class SettingsPatchDTO(BaseModel):  # type: ignore[explicit-any]
    """Settings patch request body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tts: TTSSettingsPatchDTO | None = None
    pane_theming_mode: PaneThemingMode | None = None


class MessageDTO(BaseModel):  # type: ignore[explicit-any]
    """A single structured message from a session transcript."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "system"]
    type: Literal["text", "compaction", "tool_use", "tool_result", "thinking"]
    text: str
    timestamp: str | None = None
    entry_index: int = 0
    file_index: int = 0


class SessionMessagesDTO(BaseModel):  # type: ignore[explicit-any]
    """Response for GET /sessions/{session_id}/messages."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent: str | None = None
    messages: list[MessageDTO] = Field(default_factory=list)


class JobDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for job info."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: Literal["agent", "script"]
    schedule: str | None = None
    last_run: str | None = None
    status: str
