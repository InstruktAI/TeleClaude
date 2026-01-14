"""API request/response models for REST adapter."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from teleclaude.core.models import SessionSummary


class CreateSessionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to create a new session."""

    model_config = ConfigDict(frozen=True)

    computer: str = Field(..., min_length=2)
    project_dir: str = Field(..., min_length=2)
    agent: Literal["claude", "gemini", "codex"] = "claude"
    thinking_mode: Literal["fast", "med", "slow"] = "slow"
    title: str | None = None
    message: str | None = None
    auto_command: str | None = None


class CreateSessionResponseDTO(BaseModel):  # type: ignore[explicit-any]
    """Response from session creation."""

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error"]
    session_id: str | None = None
    tmux_session_name: str | None = None
    error: str | None = None


class SendMessageRequest(BaseModel):  # type: ignore[explicit-any]
    """Request to send a message to a session."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(..., min_length=1)


class SessionSummaryDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for session summary in lists."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    thinking_mode: str
    active_agent: str | None = None
    status: str
    created_at: str | None = None
    last_activity: str | None = None
    last_input: str | None = None
    last_output: str | None = None
    tmux_session_name: str | None = None
    initiator_session_id: str | None = None
    computer: str | None = None

    @classmethod
    def from_core(cls, summary: "SessionSummary", computer: str | None = None) -> "SessionSummaryDTO":
        """Map from core SessionSummary dataclass."""
        return cls(
            session_id=summary.session_id,
            origin_adapter=summary.origin_adapter,
            title=summary.title,
            working_directory=summary.working_directory,
            thinking_mode=summary.thinking_mode,
            active_agent=summary.active_agent,
            status=summary.status,
            created_at=summary.created_at,
            last_activity=summary.last_activity,
            last_input=summary.last_input,
            last_output=summary.last_output,
            tmux_session_name=summary.tmux_session_name,
            initiator_session_id=summary.initiator_session_id,
            computer=computer,
        )


class SessionDataDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for session transcript data."""

    model_config = ConfigDict(frozen=True)

    status: str
    session_id: str | None = None
    transcript: str | None = None
    messages: str | None = None  # Alias for transcript in some contexts
    last_activity: str | None = None
    working_directory: str | None = None
    project_dir: str | None = None  # Alias for working_directory
    created_at: str | None = None
    error: str | None = None


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


class ProjectWithTodosDTO(ProjectDTO):  # type: ignore[explicit-any]
    """DTO for project with its todos."""

    model_config = ConfigDict(frozen=True)

    todos: list[TodoDTO] = Field(default_factory=list)


class AgentAvailabilityDTO(BaseModel):  # type: ignore[explicit-any]
    """DTO for agent availability."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["claude", "gemini", "codex"]
    available: bool | None
    unavailable_until: str | None = None
    reason: str | None = None
    error: str | None = None


# WebSocket Event DTOs


class SessionsInitialDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for sessions_initial event."""

    model_config = ConfigDict(frozen=True)

    sessions: list[SessionSummaryDTO]
    computer: str | None = None


class SessionsInitialEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for initial sessions list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["sessions_initial"] = "sessions_initial"
    data: SessionsInitialDataDTO


class ProjectsInitialDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for projects_initial event."""

    model_config = ConfigDict(frozen=True)

    projects: list[ProjectDTO | ProjectWithTodosDTO]
    computer: str | None = None


class ProjectsInitialEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for initial projects list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["projects_initial", "preparation_initial"]
    data: ProjectsInitialDataDTO


class SessionUpdateEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for session updates."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_updated", "session_created"]
    data: SessionSummaryDTO


class SessionRemovedDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for session_removed event."""

    model_config = ConfigDict(frozen=True)

    session_id: str


class SessionRemovedEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for session removal."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_removed"] = "session_removed"
    data: SessionRemovedDataDTO


class RefreshDataDTO(BaseModel):  # type: ignore[explicit-any]
    """Data for refresh events."""

    model_config = ConfigDict(frozen=True)

    computer: str | None = None
    project_path: str | None = None


class RefreshEventDTO(BaseModel):  # type: ignore[explicit-any]
    """WebSocket event for generic refreshes."""

    model_config = ConfigDict(frozen=True)

    event: Literal["computer_updated", "project_updated", "projects_updated", "todos_updated"]
    data: RefreshDataDTO
