"""API request/response models for API server."""

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from teleclaude.agent_registry import AgentName
from teleclaude.api_models_chiptunes import ChiptunesStatusDTO
from teleclaude.api_models_identity import OwnershipSurfaceDTO, PersonChipDTO
from teleclaude.api_session_attachment import SessionAttachmentDestinationDTO
from teleclaude.api_session_readiness import SessionReadinessDTOFields
from teleclaude.config.job_scope import JobScope
from teleclaude.config.schema import JobType, MessagingChannel
from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.session_status import (
    AgentStatusReason,
    AgentStatusValue,
    HostPaneViewerAdmission,
    SessionSelectionDisposition,
)
from teleclaude.cron_status import JobRunStatus
from teleclaude.session_fields import SESSION_PRINCIPAL_FIELD, SessionDTOIdentityFields, SessionDTOTimestampFields
from teleclaude.types.github_issue import GITHUB_ISSUE_FIELD, GitHubIssueReference
from teleclaude.types.todo_kind import TODO_KIND_USAGE, TodoKind

_TODO_KIND_FIELD = "kind"
_SESSION_SUBJECT_OWNER_FIELD = "subject_owner"
_TODO_KIND_REQUIRED_ERROR = f"kind is required; valid kinds: {TODO_KIND_USAGE}"
PEOPLE_API_PREFIX = "/api/people"
PERSON_MESSAGE_ROUTE = "/message"
PERSON_MESSAGE_PATH = PEOPLE_API_PREFIX + PERSON_MESSAGE_ROUTE
_CARRIED_FILE_INCOMPLETE_ERROR = "A carried file names both file_name and file_content_b64, or neither."
_CARRIED_FILE_AND_PATH_ERROR = "A request names a file by path or carries its content, not both."
_AUDIO_STT_SOURCE_EXCLUSIVE_ERROR = "Exactly one of url or path is required."

if TYPE_CHECKING:
    from teleclaude.core.models import SessionSnapshot


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    model_config = ConfigDict(frozen=True)

    computer: str = Field(..., min_length=2)
    project_path: str = Field(..., min_length=2)
    launch_kind: Literal["empty", "agent", "agent_then_message", "agent_resume"] = "agent"
    agent: AgentName | None = None
    thinking_mode: Literal["fast", "med", "slow", "default"] | None = None
    message: str | None = None
    title: str | None = None
    direct: bool = False
    skip_listener_registration: bool = False
    native_session_id: str | None = None
    subdir: str | None = None
    company: str | None = None
    metadata: dict[str, object] | None = None  # guard: loose-dict
    origin: str | None = None
    origin_metadata: dict[str, object] | None = None  # guard: loose-dict
    command_input_mode: CommandInputMode = CommandInputMode.ORDINARY
    command_input_source_text: str | None = None


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
    agent: AgentName | None = None
    error: str | None = None
    routing_explanation: str | None = None
    routing_reason: str | None = None


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


class SetReminderRequest(BaseModel):
    """Session-local reminder set request; ownership comes from authentication."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
    intent: str | None = Field(default=None, min_length=1)
    after: str | None = Field(default=None, min_length=1)
    at: str | None = Field(default=None, min_length=1)
    repeat: bool = False
    target_slug: str | None = Field(default=None, min_length=1)


class ReminderDTO(BaseModel):
    """Current live reminder aggregate returned by list and session inspection."""

    model_config = ConfigDict(frozen=True)

    slug: str
    profile: str | None = None
    intent: str
    trigger: Literal["time", "agent_event"]
    recurrence: Literal["one_shot", "recurring"]
    event_anchor: str | None = None
    interval_seconds: float | None = None
    armed_at: str
    next_fire_at: str | None = None
    generation: int


class ReminderEntryDTO(BaseModel):
    """One material reminder lifecycle transition."""

    model_config = ConfigDict(frozen=True)

    entry_id: int
    slug: str
    transition: Literal["armed", "replaced", "cancelled", "firing"]
    profile: str | None = None
    intent: str
    trigger: Literal["time", "agent_event"]
    recurrence: Literal["one_shot", "recurring"]
    event_anchor: str | None = None
    interval_seconds: float | None = None
    armed_at: str
    occurred_at: str
    next_fire_at: str | None = None
    generation: int


class ReminderMutationResponseDTO(BaseModel):
    """Agent-facing result for a set or effective cancellation."""

    model_config = ConfigDict(frozen=True)

    outcome: Literal["success", "already_absent"]
    entry: ReminderEntryDTO | None = None
    presentation: str | None = None


class KeysRequest(BaseModel):
    """Request to send a key command to a session."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(..., min_length=1)
    count: int | None = Field(default=None, ge=1)


class FileUploadRequest(BaseModel):
    """Request to send a file input to a session."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    caption: str | None = None
    file_size: int = 0


class SessionDTO(SessionReadinessDTOFields, SessionDTOTimestampFields, SessionDTOIdentityFields):
    """DTO for session data in API responses."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    last_input_origin: str | None = None
    title: str
    project_path: str | None = None
    subdir: str | None = None
    config_subject: str | None = None
    subject_owner: str | None = None
    person_chip: PersonChipDTO | None = None
    command: str | None = None
    working_slug: str | None = None
    github_issue: GitHubIssueReference | None = None
    thinking_mode: str | None = None
    active_agent: str | None = None
    status: str
    visibility: str = "private"
    role: str | None = None
    job: str | None = None
    agent_status: AgentStatusValue | None = None
    agent_status_reason: AgentStatusReason | None = None
    agent_status_since: str | None = None
    host_viewer_admission: HostPaneViewerAdmission | None = None
    selection_disposition: SessionSelectionDisposition | None = None
    attachment_destination: SessionAttachmentDestinationDTO | None = None
    next_reminder_slug: str | None = None
    next_reminder_at: str | None = None
    conversation_url: str | None = None

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
                _SESSION_SUBJECT_OWNER_FIELD: session.subject_owner,
                "command": session.command,
                "working_slug": session.working_slug,
                GITHUB_ISSUE_FIELD: session.github_issue,
                "thinking_mode": session.thinking_mode,
                "active_agent": session.active_agent,
                "status": session.status,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "closed_at": session.closed_at,
                "last_input": session.last_input,
                "last_input_at": session.last_input_at,
                "last_agent_stop_at": session.last_agent_stop_at,
                "last_agent_idle_at": session.last_agent_idle_at,
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
                SESSION_PRINCIPAL_FIELD: session.principal,
                "visibility": session.visibility,
                "role": session.role,
                "job": session.job,
                "agent_status": session.agent_status,
                "agent_status_reason": session.agent_status_reason,
                "agent_status_since": session.agent_status_since,
                "next_reminder_slug": session.next_reminder_slug,
                "next_reminder_at": session.next_reminder_at,
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
    role: Literal["admin", "member"] = "member"
    expertise: dict[str, str | dict[str, str]] | None = None


class ComputerDTO(BaseModel):
    """DTO for computer info."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    user: str | None = None
    host: str | None = None
    is_local: bool
    tmux_binary: str | None = None


class ProjectDTO(BaseModel):
    """DTO for project info."""

    model_config = ConfigDict(frozen=True)

    computer: str
    name: str
    path: str
    description: str | None = None
    subject: str | None = None
    owner: str | None = None


class AddProjectRequest(BaseModel):
    """Request to adopt one folder as a local registry entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1)


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
    artifact_updated_at: dict[str, str] = Field(default_factory=dict)
    version_total: int = 0
    after: list[str] = Field(default_factory=list)
    group: str | None = None
    # The holder's durable row id, resolved alongside `group` (its display
    # label). Tree-nesting keys on this — never on `group`/`slug` — because a
    # retained delivered/removed row may legitimately share a slug with a
    # live holder's synthetic label node.
    group_id: str | None = None
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
    prepared_session_id: str | None = None
    todo_id: str | None = None
    removed_at: str | None = None
    lineage: str | None = None
    entry_point: str | None = None
    human_involved: bool = False
    context: str | None = None
    person_chip: PersonChipDTO | None = None


class BugListEntryDTO(BaseModel):
    """One active bug and its lifecycle progress label."""

    model_config = ConfigDict(frozen=True)

    slug: str
    status: str


class ProjectWithTodosDTO(ProjectDTO):
    """DTO for project with its todos."""

    model_config = ConfigDict(frozen=True)

    todos: list[TodoDTO] = Field(default_factory=list)
    has_todo: bool = False


class ModelAvailabilityDTO(BaseModel):
    """One active model-scoped availability record."""

    model_config = ConfigDict(frozen=True)

    model: str
    status: AgentAvailabilityStatus
    status_until: str | None
    reason: str | None
    unavailable_until: str | None = None


class ModelAvailabilityDeltaDTO(BaseModel):
    """An upsert or removal of one model-scoped availability record."""

    model_config = ConfigDict(frozen=True)

    model: str
    status: AgentAvailabilityStatus
    status_until: str | None = None
    active: bool
    unavailable_until: str | None = None
    reason: str | None = None


class AgentAvailabilityDTO(BaseModel):
    """DTO for agent availability."""

    model_config = ConfigDict(frozen=True)

    agent: AgentName
    available: bool | None
    enabled: bool = True
    status: AgentAvailabilityStatus | None = None
    status_until: str | None = None
    unavailable_until: str | None = None
    degraded_until: str | None = None
    reason: str | None = None
    error: str | None = None
    models: list[ModelAvailabilityDTO] = Field(default_factory=list)
    model_delta: ModelAvailabilityDeltaDTO | None = None


class SetAgentStatusRequest(BaseModel):
    """Request to set agent status."""

    model_config = ConfigDict(frozen=True)

    status: Literal["available", "degraded", "unavailable"]
    reason: str | None = None
    duration_minutes: int | None = None


class TodoDumpRequest(BaseModel):
    """Request body for POST /todos/dump, answered with a filing receipt.

    ``kind`` selects the lifecycle entry point:
      - "feature": content is the "input" artifact; enters intake (authors a PRD).
      - "change":  content is the "input" artifact; enters plan drafting (no PRD).
      - "bug":     content is the "input" artifact; skips prepare and enters the fix lane.
      - "task":    content is the "input" artifact; created unheld and tracked by task-plan.

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
    kind: TodoKind
    after: list[str] | None = None
    schedule: str | None = None
    cwd: str | None = None
    icebox: bool = False
    group: str | None = None
    plan: bool = False
    hold: bool = False
    reason: str | None = None
    human_involved: bool = False
    human_involvement_reason: str | None = None
    client_request_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _require_kind(cls, data: object) -> object:
        if isinstance(data, dict) and _TODO_KIND_FIELD not in data:
            raise ValueError(_TODO_KIND_REQUIRED_ERROR)
        return data


class PersonMessageDeliveryResponse(BaseModel):
    """One successful person-addressed delivery in the CLI response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recipient: str = Field(min_length=1)
    channel: MessagingChannel
    message_id: str | None


class PersonMessageFailureResponse(BaseModel):
    """One person-addressed delivery failure in the CLI response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recipient: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class PersonMessageResponse(BaseModel):
    """Successful person-addressed message result returned to the CLI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"]
    deliveries: list[PersonMessageDeliveryResponse] = Field(min_length=1)
    failures: list[PersonMessageFailureResponse]


class PersonMessageRequest(BaseModel):
    """Request body for POST /api/people/message.

    ``file`` names a path on the computer that runs the request. A request another computer carries
    to the master cannot name a path there, so it carries the file's name and content
    (``file_name``, ``file_content_b64``) and the originating session's Discord backlink
    (``origin_backlink_url``) instead; both are set only by the requesting computer's daemon.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    recipient: str | None = Field(default=None, min_length=1)
    text: str = Field(..., min_length=1)
    file: str | None = None
    subject: str | None = None
    channel: MessagingChannel | None = None
    file_name: str | None = Field(default=None, min_length=1)
    file_content_b64: str | None = None
    origin_backlink_url: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _carried_file_is_whole(self) -> "PersonMessageRequest":
        if (self.file_name is None) != (self.file_content_b64 is None):
            raise ValueError(_CARRIED_FILE_INCOMPLETE_ERROR)
        if self.file is not None and self.file_content_b64 is not None:
            raise ValueError(_CARRIED_FILE_AND_PATH_ERROR)
        return self


class AudioSTTFailureKind(StrEnum):
    """Closed set of supplied-audio transcription failure outcomes."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    UNSUPPORTED_MEDIA = "unsupported_media"
    NO_STT_SERVICE = "no_stt_service"
    TRANSCRIPTION_FAILED = "transcription_failed"


class AudioSTTResponseStatus(StrEnum):
    """Closed status vocabulary for supplied-audio transcription responses."""

    OK = "ok"
    FAILED = "failed"


class AudioSTTRequest(BaseModel):
    """Request to transcribe one supplied URL or absolute local path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str | None = None
    path: str | None = None
    language: str | None = None

    @model_validator(mode="after")
    def _require_one_source(self) -> "AudioSTTRequest":
        if (self.url is None) == (self.path is None):
            raise ValueError(_AUDIO_STT_SOURCE_EXCLUSIVE_ERROR)
        return self


class AudioSTTOkResponse(BaseModel):
    """Successful transcript returned to the requesting CLI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[AudioSTTResponseStatus.OK]
    transcript: str


class AudioSTTFailureResponse(BaseModel):
    """Typed failure returned to the requesting CLI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[AudioSTTResponseStatus.FAILED]
    failure_kind: AudioSTTFailureKind
    reason: str


AudioSTTResponse = AudioSTTOkResponse | AudioSTTFailureResponse


# WebSocket Event DTOs


class SessionsInitialDataDTO(BaseModel):
    """Data for sessions_initial event."""

    model_config = ConfigDict(frozen=True)

    sessions: list[SessionDTO]
    computer: str | None = None
    ownership: OwnershipSurfaceDTO | None = None


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
    ownership: OwnershipSurfaceDTO | None = None


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


class SessionLifecycleStatusEventDTO(BaseModel):
    """WebSocket event for canonical session lifecycle status transitions.

    Canonical contract fields:
      status: accepted, unknown, active, idle, blocked, stalled,
              closed, error, escalated, or escalation_ended.
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
                      agent_output_update, agent_stop).
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

    type: Literal["pre_tool_use"] = "pre_tool_use"
    tool_name: str | None = None
    tool_preview: str | None = None


class AgentStopActivityEventDTO(BaseAgentActivityEventDTO):
    """WebSocket event for agent stop activity."""

    type: Literal["agent_stop"] = "agent_stop"
    summary: str | None = None


type AgentActivityEventDTO = UserPromptSubmitActivityEventDTO | ToolUseActivityEventDTO | AgentStopActivityEventDTO


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
    type: Literal["text", "compaction", "pre_tool_use", "tool_result", "thinking"]
    text: str
    timestamp: str | None = None
    entry_index: int = 0
    file_index: int = 0


class SessionMessagesDTO(SessionReadinessDTOFields):
    """Response for GET /sessions/{session_id}/messages."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent: str | None = None
    last_activity: str | None = None
    last_input_at: str | None = None
    last_agent_stop_at: str | None = None
    last_agent_idle_at: str | None = None
    agent_status: AgentStatusValue | None = None
    agent_status_reason: AgentStatusReason | None = None
    agent_status_since: str | None = None
    agent_status_exact: AgentStatusValue | None = None
    messages: list[MessageDTO] = Field(default_factory=list)


class JobDTO(BaseModel):
    """DTO for job info."""

    model_config = ConfigDict(frozen=True)

    name: str
    project: str
    type: JobType
    schedule: str | None = None
    last_run: str | None = None
    status: JobRunStatus
    scope: JobScope
    next_due: str | None = None


type TuiBootstrapPillar = Literal[
    "computers",
    "projects",
    "sessions",
    "availability",
    "jobs",
    "settings",
    "chiptunes",
    "ownership",
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
    ownership: OwnershipSurfaceDTO | None = None


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
    command: str = Field(..., min_length=1, description="Command name (e.g. 'build')")
    args: str = Field(default="", description="Command arguments")
    project: str = Field(..., min_length=1, description="Project path")
    agent: AgentName | None = None
    subfolder: str = ""
    thinking_mode: Literal["fast", "med", "slow"] | None = None
    detach: bool = False
    additional_context: str = ""
    company: str | None = None
    job: str | None = Field(default=None, description="Configured job name when the run is a scheduled job entry")
    manually_started: bool = Field(
        default=False,
        description="A person asked for this lifecycle start; the claim recorded for it is marked manual",
    )


class AgentStatusRequest(BaseModel):
    """Request to set agent dispatch status with an absolute ISO8601 expiry (POST /agents/{agent}/status)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["available", "unavailable", "degraded"] | None = None
    reason: str | None = None
    duration_minutes: int | None = None
    until: str | None = None
    clear: bool = False
    model: str | None = None
