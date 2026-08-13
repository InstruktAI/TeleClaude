"""API request/response models for API server."""

from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from teleclaude.config.schema import MessagingChannel
from teleclaude.session_fields import SessionDTOIdentityFields, SessionDTOTimestampFields
from teleclaude.types.todo_kind import TodoDumpKind

if TYPE_CHECKING:
    from teleclaude.core.models import SessionSnapshot


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    model_config = ConfigDict(frozen=True)

    computer: str = Field(..., min_length=2)
    project_path: str = Field(..., min_length=2)
    launch_kind: Literal["empty", "agent", "agent_then_message", "agent_resume"] = "agent"
    agent: Literal["claude", "gemini", "codex"] | None = None
    thinking_mode: Literal["fast", "med", "slow", "default"] | None = None
    message: str | None = None
    title: str | None = None
    direct: bool = False
    skip_listener_registration: bool = False
    native_session_id: str | None = None
    subdir: str | None = None
    human_email: str | None = None
    human_role: Literal["admin", "member", "contributor", "newcomer"] | None = None
    metadata: dict[str, object] | None = None  # guard: loose-dict
    origin: str | None = None
    origin_metadata: dict[str, object] | None = None  # guard: loose-dict


class CreateSessionResponseDTO(BaseModel):
    """Response from session creation."""

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error"]
    session_id: str
    tmux_session_name: str
    # Identifies which computer owns the session's tmux server. Consumers
    # (TUI attach, CLI revive) use this to decide between a local tmux split
    # and an SSH-wrapped attach. ``None`` means "treat as local" — preserves
    # behavior for older clients that don't read this field.
    computer: str | None = None
    agent: Literal["claude", "gemini", "codex"] | None = None
    error: str | None = None


class SendMessageResponseDTO(BaseModel):
    """Response from sending a message to a session."""

    model_config = ConfigDict(frozen=True)

    status: Literal["success", "error"]
    mode: Literal["work", "direct"] | None = None
    action: Literal["closed"] | None = None
    link_id: str | None = None
    link_state: Literal["created"] | None = None
    delivered_to: int | None = None
    members: int | None = None
    message: str | None = None


class SendMessageRequest(BaseModel):
    """Request to send a message to a session."""

    model_config = ConfigDict(frozen=True)

    message: str | None = Field(default=None, min_length=1)
    direct: bool = False
    close_link: bool = False

    @model_validator(mode="after")
    def _require_message_unless_close_link(self) -> "SendMessageRequest":
        if not self.close_link and self.message is None:
            raise ValueError("message required")
        return self


class KeysRequest(BaseModel):
    """Request to send a key command to a session."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(..., min_length=1)
    count: int | None = Field(default=None, ge=1)


class VoiceInputRequest(BaseModel):
    """Request to send a voice input to a session."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., min_length=1)
    duration: float | None = None
    message_id: str | None = None
    message_thread_id: int | None = None


class FileUploadRequest(BaseModel):
    """Request to send a file input to a session."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    caption: str | None = None
    file_size: int = 0


class SessionDTO(SessionDTOTimestampFields, SessionDTOIdentityFields):
    """DTO for session data in API responses."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    last_input_origin: str | None = None
    title: str
    project_path: str | None = None
    subdir: str | None = None
    working_slug: str | None = None
    thinking_mode: str | None = None
    active_agent: str | None = None
    status: str
    visibility: str = "private"
    system_role: str | None = None
    job: str | None = None
    agent_status: Literal["active", "idle", "unknown"] | None = None

    @classmethod
    def from_core(cls, session: "SessionSnapshot", computer: str | None = None) -> "SessionDTO":
        """Map from core SessionSnapshot dataclass."""
        payload_obj = session.to_dict() if callable(getattr(session, "to_dict", None)) else None
        if not isinstance(payload_obj, dict):
            payload_obj = {
                "session_id": session.session_id,
                "last_input_origin": session.last_input_origin,
                "title": session.title,
                "project_path": session.project_path,
                "subdir": session.subdir,
                "working_slug": session.working_slug,
                "thinking_mode": session.thinking_mode,
                "active_agent": session.active_agent,
                "status": session.status,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "closed_at": session.closed_at,
                "last_input": session.last_input,
                "last_input_at": session.last_input_at,
                "last_agent_stop_at": session.last_agent_stop_at,
                "last_output_summary": session.last_output_summary,
                "last_output_summary_at": session.last_output_summary_at,
                "last_output_digest": session.last_output_digest,
                "native_session_id": session.native_session_id,
                "tmux_session_name": session.tmux_session_name,
                "initiator_session_id": session.initiator_session_id,
                "detached": getattr(session, "detached", False),
                "computer": session.computer,
                "human_email": session.human_email,
                "human_role": session.human_role,
                "visibility": session.visibility,
                "system_role": session.system_role,
                "job": session.job,
                "agent_status": session.agent_status,
            }
        payload = dict(payload_obj)
        payload["visibility"] = session.visibility or "private"
        payload["computer"] = computer
        return cls.model_validate(payload)


class PersonDTO(BaseModel):
    """DTO for person info (safe subset — no credentials)."""

    model_config = ConfigDict(frozen=True)

    name: str
    email: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] = "member"
    expertise: dict[str, str | dict[str, str]] | None = None


class ComputerDTO(BaseModel):
    """DTO for computer info."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    user: str | None = None
    host: str | None = None
    is_local: bool


class ProjectDTO(BaseModel):
    """DTO for project info."""

    model_config = ConfigDict(frozen=True)

    computer: str
    name: str
    path: str
    description: str | None = None


class TodoDTO(BaseModel):
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
    prepare_review_verdict: str | None = None
    deferrals_status: str | None = None
    files: list[str] = Field(default_factory=list)
    version_total: int = 0
    after: list[str] = Field(default_factory=list)
    group: str | None = None
    delivered_at: str | None = None
    kind: str | None = None
    ready_since: str | None = None
    schedule: str | None = None
    task_plan_digest: str | None = None
    task_approved_digest: str | None = None
    updated_at: str | None = None
    created_at: str | None = None
    band: str | None = None
    lifecycle_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None
    hold: bool = False
    held: bool = False
    hold_source: str | None = None
    active_runner: str | None = None
    todo_id: str | None = None
    removed_at: str | None = None
    lineage: str | None = None
    entry_point: str | None = None
    human_involved: bool = False
    context: str | None = None


class OperationStatusBlockingSnippetPayload(BaseModel):
    """Machine-readable snippet blocker payload exposed by operation DTOs."""

    model_config = ConfigDict(frozen=True)

    path: str
    slug_role: str
    live_deliverer_count: int
    other_removed_deliverers: list[str]


class OperationStatusErrorPayload(BaseModel):
    """Machine-readable operation failure payload exposed by API DTOs."""

    model_config = ConfigDict(frozen=True)

    kind: str | None = None
    blocking_snippets: list[OperationStatusBlockingSnippetPayload] | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.model_dump(exclude_none=True) == other
        return super().__eq__(other)


class OperationStatusDTO(BaseModel):
    """DTO for long-running operation receipts and status payloads."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    kind: str
    state: Literal["queued", "running", "completed", "failed", "stale", "cancelled"]
    poll_after_ms: int = 0
    status_path: str
    recovery_command: str
    slug: str | None = None
    completion_event: str | None = None
    progress_phase: str | None = None
    progress_decision: str | None = None
    progress_reason: str | None = None
    result: str | None = None
    error: str | None = None
    error_payload: OperationStatusErrorPayload | None = None
    client_request_id: str | None = None


class OperationStatusPayload(TypedDict):
    """Typed dict form of the durable operation receipt payload."""

    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str
    slug: NotRequired[str]
    completion_event: NotRequired[str]
    progress_phase: NotRequired[str]
    progress_decision: NotRequired[str]
    progress_reason: NotRequired[str]
    result: NotRequired[str]
    error: NotRequired[str]
    error_payload: NotRequired[OperationStatusErrorPayload]
    client_request_id: NotRequired[str]


class ProjectWithTodosDTO(ProjectDTO):
    """DTO for project with its todos."""

    model_config = ConfigDict(frozen=True)

    todos: list[TodoDTO] = Field(default_factory=list)
    has_todo: bool = False


class AgentAvailabilityDTO(BaseModel):
    """DTO for agent availability."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["claude", "gemini", "codex"]
    available: bool | None
    status: Literal["available", "unavailable", "degraded"] | None = None
    unavailable_until: str | None = None
    degraded_until: str | None = None
    reason: str | None = None
    error: str | None = None


class SetAgentStatusRequest(BaseModel):
    """Request to set agent status."""

    model_config = ConfigDict(frozen=True)

    status: Literal["available", "degraded", "unavailable"]
    reason: str | None = None
    duration_minutes: int | None = None


class TodoDumpRequest(BaseModel):
    """Request body for POST /todos/dump.

    ``kind`` selects the lifecycle entry point when present:
      - "feature": content is the "input" artifact; enters intake (authors a PRD).
      - "change":  content is the "input" artifact; enters plan drafting (no PRD).
      - "bug":     content is the "input" artifact; skips prepare and enters the fix lane.
      - "task":    content is the "input" artifact; created unheld and tracked by task-plan.

    Omitted ``kind`` creates a kind-less todo: content is stored as immutable
    ``input`` with no lifecycle_phase and routed to /analyze-todo-input for assignment.

    ``icebox`` creates the todo parked in the icebox so the daemon's prepare
    auto-spawn is suppressed. ``group`` attaches the new todo as a child of the
    named parent slug. ``hold`` is a hidden create-time dispatch brake for
    specialist orchestration: it creates an active todo whose hold flag is set so
    the lifecycle router and runner do not claim it until it is released — not a
    parking replacement for ``--icebox``. The retired create-time fields
    ``release`` and ``silent`` are rejected (``extra="forbid"``): a stale body
    carrying them fails fast rather than silently auto-dispatching.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    kind: TodoDumpKind | None = None
    after: list[str] | None = None
    schedule: str | None = None
    cwd: str | None = None
    icebox: bool = False
    group: str | None = None
    plan: bool = False
    hold: bool = False
    human_involved: bool = False


class PersonMessageRequest(BaseModel):
    """Request body for POST /api/people/message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    file: str | None = None
    subject: str | None = None
    channel: MessagingChannel | None = None


# WebSocket Event DTOs


class SessionsInitialDataDTO(BaseModel):
    """Data for sessions_initial event."""

    model_config = ConfigDict(frozen=True)

    sessions: list[SessionDTO]
    computer: str | None = None


class SessionsInitialEventDTO(BaseModel):
    """WebSocket event for initial sessions list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["sessions_initial"] = "sessions_initial"
    data: SessionsInitialDataDTO


class ProjectsInitialDataDTO(BaseModel):
    """Data for projects_initial event."""

    model_config = ConfigDict(frozen=True)

    projects: list[ProjectWithTodosDTO | ProjectDTO]
    computer: str | None = None


class ProjectsInitialEventDTO(BaseModel):
    """WebSocket event for initial projects list."""

    model_config = ConfigDict(frozen=True)

    event: Literal["projects_initial", "preparation_initial"]
    data: ProjectsInitialDataDTO


class SessionStartedEventDTO(BaseModel):
    """WebSocket event for session creation."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_started"]
    data: SessionDTO


class SessionUpdatedEventDTO(BaseModel):
    """WebSocket event for session updates."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_updated"]
    data: SessionDTO


class SessionClosedDataDTO(BaseModel):
    """Data for session_closed event."""

    model_config = ConfigDict(frozen=True)

    session_id: str


class SessionClosedEventDTO(BaseModel):
    """WebSocket event for session closure."""

    model_config = ConfigDict(frozen=True)

    event: Literal["session_closed"] = "session_closed"
    data: SessionClosedDataDTO


class RefreshDataDTO(BaseModel):
    """Data for refresh events."""

    model_config = ConfigDict(frozen=True)

    computer: str | None = None
    project_path: str | None = None


class RefreshEventDTO(BaseModel):
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


class TodoRenamedDataDTO(BaseModel):
    """Data for todo_renamed event."""

    model_config = ConfigDict(frozen=True)

    old_slug: str = Field(..., min_length=1)
    new_slug: str = Field(..., min_length=1)
    project_path: str = Field(..., min_length=1)


class TodoRenamedEventDTO(BaseModel):
    """WebSocket event for todo slug rename."""

    model_config = ConfigDict(frozen=True)

    event: Literal["todo_renamed"] = "todo_renamed"
    data: TodoRenamedDataDTO


class ErrorEventDataDTO(BaseModel):
    """Data for error events."""

    model_config = ConfigDict(frozen=True)

    session_id: str | None = None
    message: str
    source: str | None = None
    details: dict[str, object] | None = None  # guard: loose-dict - error details vary
    severity: Literal["warning", "error", "critical"] = "error"
    retryable: bool = False
    code: str | None = None


class ErrorEventDTO(BaseModel):
    """WebSocket event for errors."""

    model_config = ConfigDict(frozen=True)

    event: Literal["error"] = "error"
    data: ErrorEventDataDTO


class ChiptunesTrackEventDTO(BaseModel):
    """WebSocket event when a new chiptunes track starts playing."""

    model_config = ConfigDict(frozen=True)

    event: Literal["chiptunes_track"] = "chiptunes_track"
    track: str
    sid_path: str = ""


class ChiptunesStatusDTO(BaseModel):
    """Current chiptunes playback state."""

    model_config = ConfigDict(frozen=True)

    playback: Literal["cold", "loading", "playing", "paused"] = "cold"
    state_version: int = 0
    loaded: bool = False
    playing: bool = False
    paused: bool = False
    position_seconds: float = 0.0
    track: str = ""
    sid_path: str = ""
    pending_command_id: str = ""
    pending_action: Literal["", "resume", "pause", "next", "prev"] = ""


class ChiptunesStateEventDTO(BaseModel):
    """WebSocket event for chiptunes playback state transitions."""

    model_config = ConfigDict(frozen=True)

    event: Literal["chiptunes_state"] = "chiptunes_state"
    playback: Literal["cold", "loading", "playing", "paused"] = "cold"
    state_version: int = 0
    loaded: bool = False
    playing: bool = False
    paused: bool = False
    position_seconds: float = 0.0
    track: str = ""
    sid_path: str = ""
    pending_command_id: str = ""
    pending_action: Literal["", "resume", "pause", "next", "prev"] = ""


class ChiptunesCommandReceiptDTO(BaseModel):
    """Receipt for accepted chiptunes command (asynchronous execution)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"] = "accepted"
    command_id: str
    action: Literal["resume", "pause", "next", "prev"]


class SessionLifecycleStatusEventDTO(BaseModel):
    """WebSocket event for canonical session lifecycle status transitions.

    Canonical contract fields (ucap-truthful-session-status):
      status: Lifecycle status vocabulary value (accepted, active,
              active_output, completed, error, closed).
      reason: Reason code for the transition.
      last_activity_at: ISO 8601 UTC timestamp of last observed activity (optional).
      message_intent: Routing intent (ctrl_status).
      delivery_scope: Routing scope (CTRL).
    """

    model_config = ConfigDict(frozen=True)

    event: Literal["session_status"] = "session_status"
    session_id: str
    status: str  # canonical status vocabulary value
    reason: str
    timestamp: str
    last_activity_at: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


class AgentAvailabilityEventDTO(BaseModel):
    """WebSocket event for live agent availability changes."""

    model_config = ConfigDict(frozen=True)

    event: Literal["agent_availability"] = "agent_availability"
    data: AgentAvailabilityDTO


class BaseAgentActivityEventDTO(BaseModel):
    """Base WebSocket event for agent activity.

    Canonical contract fields (ucap-canonical-contract):
      canonical_type: stable outbound vocabulary type (user_prompt_submit,
                      agent_output_update, agent_output_stop).
      message_intent: routing intent (ctrl_activity).
      delivery_scope:  routing scope (CTRL).
    """

    model_config = ConfigDict(frozen=True)

    event: Literal["agent_activity"] = "agent_activity"
    session_id: str
    timestamp: str | None = None
    # Canonical contract fields (optional; present when produced via activity_contract)
    canonical_type: str | None = None
    message_intent: str | None = None
    delivery_scope: str | None = None


class UserPromptSubmitActivityEventDTO(BaseAgentActivityEventDTO):
    """WebSocket event for user prompt submit activity."""

    type: Literal["user_prompt_submit"] = "user_prompt_submit"


class ToolUseActivityEventDTO(BaseAgentActivityEventDTO):
    """WebSocket event for tool use activity."""

    type: Literal["tool_use"] = "tool_use"
    tool_name: str | None = None
    tool_preview: str | None = None


class AgentStopActivityEventDTO(BaseAgentActivityEventDTO):
    """WebSocket event for agent stop activity."""

    type: Literal["agent_stop"] = "agent_stop"
    summary: str | None = None


type AgentActivityEventDTO = UserPromptSubmitActivityEventDTO | ToolUseActivityEventDTO | AgentStopActivityEventDTO


class OperationCompletedEventDTO(BaseModel):
    """WebSocket event for operation completion (success or failure)."""

    model_config = ConfigDict(frozen=True)

    event: Literal[
        "operation.todo_work.completed",
        "operation.task_run.completed",
        "operation.todo_integrate.completed",
        "operation.todo_create.completed",
        "operation.todo_prepare.completed",
        "operation.todo_remove.completed",
        "operation.todo_rename.completed",
    ]
    operation_id: str
    error: str | None = None


class TTSSettingsDTO(BaseModel):
    """TTS section of settings response."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False


class SettingsDTO(BaseModel):
    """Runtime settings response."""

    model_config = ConfigDict(frozen=True)

    tts: TTSSettingsDTO


class TTSSettingsPatchDTO(BaseModel):
    """TTS section of settings patch request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool | None = None


class SettingsPatchDTO(BaseModel):
    """Settings patch request body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tts: TTSSettingsPatchDTO | None = None


class MessageDTO(BaseModel):
    """A single structured message from a session transcript."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "system"]
    type: Literal["text", "compaction", "tool_use", "tool_result", "thinking"]
    text: str
    timestamp: str | None = None
    entry_index: int = 0
    file_index: int = 0


class SessionMessagesDTO(BaseModel):
    """Response for GET /sessions/{session_id}/messages."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent: str | None = None
    last_activity: str | None = None
    last_input_at: str | None = None
    last_agent_stop_at: str | None = None
    agent_status: Literal["active", "idle", "unknown"] | None = None
    messages: list[MessageDTO] = Field(default_factory=list)


class JobDTO(BaseModel):
    """DTO for job info."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: Literal["agent", "script"]
    schedule: str | None = None
    last_run: str | None = None
    status: str


type TuiBootstrapPillar = Literal[
    "computers",
    "projects",
    "sessions",
    "availability",
    "jobs",
    "settings",
    "chiptunes",
]


class TuiBootstrapErrorDTO(BaseModel):
    """A recoverable per-pillar bootstrap failure."""

    model_config = ConfigDict(frozen=True)

    pillar: TuiBootstrapPillar
    message: str
    retryable: bool = True


class TuiBootstrapDataDTO(BaseModel):
    """Optional TUI bootstrap payload fields.

    Missing fields mean that pillar was not requested or failed. Clients must
    merge present fields into existing state instead of treating missing fields
    as empty authoritative snapshots.
    """

    model_config = ConfigDict(frozen=True)

    computers: list[ComputerDTO] | None = None
    projects_with_todos: list[ProjectWithTodosDTO] | None = None
    sessions: list[SessionDTO] | None = None
    availability: dict[str, AgentAvailabilityDTO] | None = None
    jobs: list[JobDTO] | None = None
    settings: SettingsDTO | None = None
    chiptunes: ChiptunesStatusDTO | None = None


class TuiBootstrapDTO(BaseModel):
    """TUI aggregate bootstrap response with partial-success semantics."""

    model_config = ConfigDict(frozen=True)

    requested: list[TuiBootstrapPillar]
    data: TuiBootstrapDataDTO = Field(default_factory=TuiBootstrapDataDTO)
    errors: list[TuiBootstrapErrorDTO] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def complete(self) -> bool:
        """Return True when every requested pillar succeeded."""
        return not self.errors


class RunSessionRequest(BaseModel):
    """Request to run an agent command in a new session (POST /sessions/run)."""

    model_config = ConfigDict(frozen=True)

    computer: str = Field(default="local")
    command: str = Field(..., min_length=1, description="Slash command (e.g. '/next-build')")
    args: str = Field(default="", description="Command arguments")
    project: str = Field(..., min_length=1, description="Project path")
    agent: Literal["claude", "gemini", "codex"] = "claude"
    subfolder: str = ""
    thinking_mode: Literal["fast", "med", "slow"] = "slow"
    detach: bool = False
    additional_context: str = ""


class SendResultRequest(BaseModel):
    """Request to send a formatted result to the session's user (POST /sessions/self/result)."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(..., min_length=1)
    output_format: Literal["markdown", "html"] = "markdown"


class RenderWidgetRequest(BaseModel):
    """Request to render a rich widget expression (POST /sessions/self/widget)."""

    model_config = ConfigDict(frozen=True)

    data: dict[str, object]  # guard: loose-dict - widget expression blob


class EscalateRequest(BaseModel):
    """Request to escalate a customer session to Discord (POST /sessions/self/escalate)."""

    model_config = ConfigDict(frozen=True)

    customer_name: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    context_summary: str | None = None


class AgentStatusRequest(BaseModel):
    """Request to set agent dispatch status with an absolute ISO8601 expiry (POST /agents/{agent}/status)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["available", "unavailable", "degraded"] | None = None
    reason: str | None = None
    duration_minutes: int | None = None
    until: str | None = None
    clear: bool = False
