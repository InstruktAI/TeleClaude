"""Characterization tests for teleclaude.api_models — pins public boundary behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from teleclaude.api_models import (
    AgentActivityEventDTO,
    AgentAvailabilityDTO,
    AgentStatusRequest,
    ChiptunesCommandReceiptDTO,
    ChiptunesStateEventDTO,
    ChiptunesStatusDTO,
    ChiptunesTrackEventDTO,
    ComputerDTO,
    CreateSessionRequest,
    CreateSessionResponseDTO,
    ErrorEventDataDTO,
    ErrorEventDTO,
    EscalateRequest,
    FileUploadRequest,
    JobDTO,
    KeysRequest,
    MessageDTO,
    OperationStatusDTO,
    OperationStatusPayload,
    PersonDTO,
    ProjectDTO,
    ProjectsInitialDataDTO,
    ProjectsInitialEventDTO,
    ProjectWithTodosDTO,
    RefreshDataDTO,
    RefreshEventDTO,
    RenderWidgetRequest,
    RunSessionRequest,
    SendMessageRequest,
    SendResultRequest,
    SessionClosedDataDTO,
    SessionClosedEventDTO,
    SessionDTO,
    SessionLifecycleStatusEventDTO,
    SessionMessagesDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionUpdatedEventDTO,
    SetAgentStatusRequest,
    SettingsDTO,
    SettingsPatchDTO,
    TodoDTO,
    TTSSettingsDTO,
    TTSSettingsPatchDTO,
    VoiceInputRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_snapshot(
    *,
    session_id: str = "sess-001",
    title: str = "Test Session",
    status: str = "active",
    visibility: str | None = "private",
    session_metadata: object = None,
    **kwargs: object,
) -> MagicMock:
    """Build a minimal SessionSnapshot-like mock for from_core tests."""
    snap = MagicMock()
    snap.session_id = session_id
    snap.last_input_origin = None
    snap.title = title
    snap.project_path = None
    snap.subdir = None
    snap.thinking_mode = None
    snap.active_agent = None
    snap.status = status
    snap.created_at = None
    snap.last_activity = None
    snap.closed_at = None
    snap.last_input = None
    snap.last_input_at = None
    snap.last_output_summary = None
    snap.last_output_summary_at = None
    snap.last_output_digest = None
    snap.native_session_id = None
    snap.tmux_session_name = None
    snap.initiator_session_id = None
    snap.human_email = None
    snap.human_role = None
    snap.visibility = visibility
    snap.session_metadata = session_metadata
    for k, v in kwargs.items():
        setattr(snap, k, v)
    return snap


# ---------------------------------------------------------------------------
# CreateSessionRequest
# ---------------------------------------------------------------------------


class TestCreateSessionRequest:
    """Pins CreateSessionRequest field constraints and defaults."""

    @pytest.mark.unit
    def test_valid_request_constructs(self):
        """Minimum required fields produce a valid request object."""
        req = CreateSessionRequest(computer="myhost", project_path="/srv/project")
        assert req.computer == "myhost"
        assert req.project_path == "/srv/project"
        assert req.launch_kind == "agent"
        assert req.direct is False

    @pytest.mark.unit
    def test_computer_min_length_enforced(self):
        """computer shorter than 2 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            CreateSessionRequest(computer="x", project_path="/srv/project")

    @pytest.mark.unit
    def test_project_path_min_length_enforced(self):
        """project_path shorter than 2 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            CreateSessionRequest(computer="myhost", project_path="/")

    @pytest.mark.unit
    def test_frozen_model_rejects_mutation(self):
        """Assigning to a frozen model attribute raises ValidationError."""
        req = CreateSessionRequest(computer="myhost", project_path="/srv/project")
        with pytest.raises(ValidationError):
            req.computer = "changed"

    @pytest.mark.unit
    def test_optional_fields_default_to_none(self):
        """Optional fields are None when not provided."""
        req = CreateSessionRequest(computer="myhost", project_path="/srv/project")
        assert req.agent is None
        assert req.thinking_mode is None
        assert req.message is None
        assert req.metadata is None

    @pytest.mark.unit
    def test_launch_kind_literal_enforced(self):
        """Invalid launch_kind value raises ValidationError."""
        with pytest.raises(ValidationError):
            CreateSessionRequest(computer="myhost", project_path="/srv/project", launch_kind="invalid")


# ---------------------------------------------------------------------------
# CreateSessionResponseDTO
# ---------------------------------------------------------------------------


class TestCreateSessionResponseDTO:
    """Pins CreateSessionResponseDTO field types and defaults."""

    @pytest.mark.unit
    def test_success_response_constructs(self):
        """A success response is constructable with required fields."""
        dto = CreateSessionResponseDTO(
            status="success",
            session_id="sess-123",
            tmux_session_name="tc_sess-123",
        )
        assert dto.status == "success"
        assert dto.agent is None
        assert dto.error is None

    @pytest.mark.unit
    def test_error_response_constructs(self):
        """An error response carries the error field."""
        dto = CreateSessionResponseDTO(
            status="error",
            session_id="",
            tmux_session_name="",
            error="something went wrong",
        )
        assert dto.status == "error"
        assert dto.error == "something went wrong"


# ---------------------------------------------------------------------------
# SendMessageRequest — model_validator
# ---------------------------------------------------------------------------


class TestSendMessageRequest:
    """Pins SendMessageRequest._require_message_unless_close_link validator."""

    @pytest.mark.unit
    def test_message_accepted(self):
        """A non-empty message is valid."""
        req = SendMessageRequest(message="hello")
        assert req.message == "hello"
        assert req.close_link is False

    @pytest.mark.unit
    def test_close_link_without_message_accepted(self):
        """close_link=True is valid without a message."""
        req = SendMessageRequest(close_link=True)
        assert req.close_link is True
        assert req.message is None

    @pytest.mark.unit
    def test_no_message_no_close_link_raises(self):
        """Neither message nor close_link raises ValidationError."""
        with pytest.raises(ValidationError):
            SendMessageRequest()

    @pytest.mark.unit
    def test_close_link_with_message_accepted(self):
        """Both message and close_link=True is valid."""
        req = SendMessageRequest(message="bye", close_link=True)
        assert req.message == "bye"
        assert req.close_link is True


# ---------------------------------------------------------------------------
# KeysRequest
# ---------------------------------------------------------------------------


class TestKeysRequest:
    """Pins KeysRequest field constraints."""

    @pytest.mark.unit
    def test_valid_key_no_count(self):
        """A key with no count is valid."""
        req = KeysRequest(key="Enter")
        assert req.key == "Enter"
        assert req.count is None

    @pytest.mark.unit
    def test_count_ge_1_enforced(self):
        """count=0 raises ValidationError (ge=1 constraint)."""
        with pytest.raises(ValidationError):
            KeysRequest(key="Up", count=0)

    @pytest.mark.unit
    def test_count_1_accepted(self):
        """count=1 is the minimum valid value."""
        req = KeysRequest(key="Up", count=1)
        assert req.count == 1


# ---------------------------------------------------------------------------
# SessionDTO.from_core
# ---------------------------------------------------------------------------


class TestSessionDTOFromCore:
    """Pins SessionDTO.from_core field mapping behavior."""

    @pytest.mark.unit
    def test_basic_fields_mapped_correctly(self):
        """from_core maps session_id, title, status from snapshot."""
        snap = _make_session_snapshot(session_id="s-1", title="My Session", status="active")
        dto = SessionDTO.from_core(snap, computer="host-a")
        assert dto.session_id == "s-1"
        assert dto.title == "My Session"
        assert dto.status == "active"
        assert dto.computer == "host-a"

    @pytest.mark.unit
    def test_session_metadata_none_produces_none(self):
        """When session_metadata is None, the DTO field is None."""
        snap = _make_session_snapshot(session_metadata=None)
        dto = SessionDTO.from_core(snap)
        assert dto.session_metadata is None

    @pytest.mark.unit
    def test_session_metadata_serialized_as_dict(self):
        """When session_metadata is a dataclass, from_core converts it to a dict."""
        from teleclaude.core.models import SessionMetadata

        meta = SessionMetadata(system_role="worker", job=None, human_email=None, human_role=None, principal=None)
        snap = _make_session_snapshot(session_metadata=meta)
        dto = SessionDTO.from_core(snap)
        assert isinstance(dto.session_metadata, dict)
        assert dto.session_metadata["system_role"] == "worker"

    @pytest.mark.unit
    def test_visibility_none_falls_back_to_private(self):
        """When visibility is None on snapshot, DTO visibility is 'private'."""
        snap = _make_session_snapshot(visibility=None)
        dto = SessionDTO.from_core(snap)
        assert dto.visibility == "private"

    @pytest.mark.unit
    def test_visibility_set_propagates(self):
        """Non-None visibility propagates from snapshot to DTO."""
        snap = _make_session_snapshot(visibility="public")
        dto = SessionDTO.from_core(snap)
        assert dto.visibility == "public"

    @pytest.mark.unit
    def test_computer_param_overrides_snapshot_computer(self):
        """computer argument to from_core is used (not snapshot.computer)."""
        snap = _make_session_snapshot()
        dto = SessionDTO.from_core(snap, computer="override-host")
        assert dto.computer == "override-host"

    @pytest.mark.unit
    def test_computer_defaults_to_none_when_not_passed(self):
        """Omitting computer results in dto.computer=None."""
        snap = _make_session_snapshot()
        dto = SessionDTO.from_core(snap)
        assert dto.computer is None


# ---------------------------------------------------------------------------
# TodoDTO
# ---------------------------------------------------------------------------


class TestTodoDTO:
    """Pins TodoDTO default field values."""

    @pytest.mark.unit
    def test_files_defaults_to_empty_list(self):
        """files field defaults to an empty list."""
        dto = TodoDTO(
            slug="my-slug",
            status="pending",
            has_requirements=False,
            has_impl_plan=False,
        )
        assert dto.files == []

    @pytest.mark.unit
    def test_after_defaults_to_empty_list(self):
        """after field defaults to an empty list."""
        dto = TodoDTO(
            slug="my-slug",
            status="pending",
            has_requirements=False,
            has_impl_plan=False,
        )
        assert dto.after == []

    @pytest.mark.unit
    def test_findings_count_defaults_to_zero(self):
        """findings_count defaults to 0."""
        dto = TodoDTO(
            slug="my-slug",
            status="pending",
            has_requirements=False,
            has_impl_plan=False,
        )
        assert dto.findings_count == 0


# ---------------------------------------------------------------------------
# OperationStatusDTO
# ---------------------------------------------------------------------------


class TestOperationStatusDTO:
    """Pins OperationStatusDTO state literal and field defaults."""

    @pytest.mark.unit
    def test_valid_state_accepted(self):
        """A valid state literal constructs the DTO."""
        dto = OperationStatusDTO(
            operation_id="op-1",
            kind="session_start",
            state="running",
            status_path="/tmp/op-1",
            recovery_command="telec operations get op-1",
        )
        assert dto.state == "running"
        assert dto.poll_after_ms == 0

    @pytest.mark.unit
    def test_invalid_state_raises(self):
        """An unknown state value raises ValidationError."""
        with pytest.raises(ValidationError):
            OperationStatusDTO(
                operation_id="op-1",
                kind="session_start",
                state="unknown_state",
                status_path="/tmp/op-1",
                recovery_command="telec operations get op-1",
            )


# ---------------------------------------------------------------------------
# TTSSettingsPatchDTO — extra="forbid"
# ---------------------------------------------------------------------------


class TestTTSSettingsPatchDTO:
    """Pins extra='forbid' behavior on patch DTOs."""

    @pytest.mark.unit
    def test_extra_field_rejected(self):
        """Extra fields not in the schema raise ValidationError."""
        with pytest.raises(ValidationError):
            TTSSettingsPatchDTO(enabled=True, unknown_field="bad")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_valid_fields_accepted(self):
        """Only enabled field is accepted."""
        dto = TTSSettingsPatchDTO(enabled=True)
        assert dto.enabled is True


class TestSettingsPatchDTO:
    """Pins SettingsPatchDTO extra='forbid' behavior."""

    @pytest.mark.unit
    def test_extra_field_rejected(self):
        """Extra fields raise ValidationError."""
        with pytest.raises(ValidationError):
            SettingsPatchDTO(tts=None, bogus="x")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_valid_patch_constructs(self):
        """Valid tts patch constructs correctly."""
        dto = SettingsPatchDTO(tts=TTSSettingsPatchDTO(enabled=False))
        assert dto.tts is not None
        assert dto.tts.enabled is False


# ---------------------------------------------------------------------------
# RunSessionRequest defaults
# ---------------------------------------------------------------------------


class TestRunSessionRequest:
    """Pins RunSessionRequest default field values."""

    @pytest.mark.unit
    def test_defaults_applied(self):
        """Default values are applied for optional fields."""
        req = RunSessionRequest(command="/next-build", project="/srv/myproject")
        assert req.computer == "local"
        assert req.agent == "claude"
        assert req.thinking_mode == "slow"
        assert req.args == ""
        assert req.subfolder == ""
        assert req.detach is False
        assert req.additional_context == ""

    @pytest.mark.unit
    def test_command_min_length_enforced(self):
        """Empty command raises ValidationError."""
        with pytest.raises(ValidationError):
            RunSessionRequest(command="", project="/srv/myproject")


# ---------------------------------------------------------------------------
# ProjectWithTodosDTO
# ---------------------------------------------------------------------------


class TestProjectWithTodosDTO:
    """Pins ProjectWithTodosDTO extended fields."""

    @pytest.mark.unit
    def test_todos_defaults_to_empty_list(self):
        """todos field defaults to empty list."""
        dto = ProjectWithTodosDTO(computer="host", name="myproject", path="/srv/myproject")
        assert dto.todos == []
        assert dto.has_roadmap is False


# ---------------------------------------------------------------------------
# ChiptunesStatusDTO defaults
# ---------------------------------------------------------------------------


class TestChiptunesStatusDTO:
    """Pins ChiptunesStatusDTO default values."""

    @pytest.mark.unit
    def test_defaults(self):
        """All fields have sensible defaults."""
        dto = ChiptunesStatusDTO()
        assert dto.playback == "cold"
        assert dto.loaded is False
        assert dto.playing is False
        assert dto.paused is False
        assert dto.position_seconds == 0.0
        assert dto.track == ""
        assert dto.pending_action == ""


# ---------------------------------------------------------------------------
# AgentAvailabilityDTO
# ---------------------------------------------------------------------------


class TestAgentAvailabilityDTO:
    """Pins AgentAvailabilityDTO field types."""

    @pytest.mark.unit
    def test_constructs_with_agent_and_available(self):
        """Agent and available fields are required."""
        dto = AgentAvailabilityDTO(agent="claude", available=True)
        assert dto.agent == "claude"
        assert dto.available is True
        assert dto.status is None

    @pytest.mark.unit
    def test_invalid_agent_raises(self):
        """Agent must be a known literal value."""
        with pytest.raises(ValidationError):
            AgentAvailabilityDTO(agent="unknown_bot", available=True)


# ---------------------------------------------------------------------------
# MessageDTO
# ---------------------------------------------------------------------------


class TestMessageDTO:
    """Pins MessageDTO field types."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """role, type, text are required."""
        dto = MessageDTO(role="user", type="text", text="hello")
        assert dto.role == "user"
        assert dto.type == "text"
        assert dto.entry_index == 0
        assert dto.file_index == 0

    @pytest.mark.unit
    def test_invalid_role_raises(self):
        """Invalid role raises ValidationError."""
        with pytest.raises(ValidationError):
            MessageDTO(role="bot", type="text", text="hi")


# ---------------------------------------------------------------------------
# VoiceInputRequest
# ---------------------------------------------------------------------------


class TestVoiceInputRequest:
    """Pins VoiceInputRequest field constraints and defaults."""

    @pytest.mark.unit
    def test_valid_request_constructs(self):
        """Minimum required fields produce a valid request."""
        req = VoiceInputRequest(file_path="/tmp/audio.wav")
        assert req.file_path == "/tmp/audio.wav"
        assert req.duration is None
        assert req.message_id is None
        assert req.message_thread_id is None

    @pytest.mark.unit
    def test_file_path_min_length_enforced(self):
        """Empty file_path raises ValidationError."""
        with pytest.raises(ValidationError):
            VoiceInputRequest(file_path="")

    @pytest.mark.unit
    def test_frozen_rejects_mutation(self):
        """Frozen model rejects attribute assignment."""
        req = VoiceInputRequest(file_path="/tmp/audio.wav")
        with pytest.raises(ValidationError):
            req.file_path = "changed"


# ---------------------------------------------------------------------------
# FileUploadRequest
# ---------------------------------------------------------------------------


class TestFileUploadRequest:
    """Pins FileUploadRequest field constraints and defaults."""

    @pytest.mark.unit
    def test_valid_request_constructs(self):
        """Required fields produce a valid request with defaults."""
        req = FileUploadRequest(file_path="/tmp/doc.pdf", filename="doc.pdf")
        assert req.file_path == "/tmp/doc.pdf"
        assert req.filename == "doc.pdf"
        assert req.caption is None
        assert req.file_size == 0

    @pytest.mark.unit
    def test_file_path_min_length_enforced(self):
        """Empty file_path raises ValidationError."""
        with pytest.raises(ValidationError):
            FileUploadRequest(file_path="", filename="doc.pdf")

    @pytest.mark.unit
    def test_filename_min_length_enforced(self):
        """Empty filename raises ValidationError."""
        with pytest.raises(ValidationError):
            FileUploadRequest(file_path="/tmp/doc.pdf", filename="")


# ---------------------------------------------------------------------------
# PersonDTO
# ---------------------------------------------------------------------------


class TestPersonDTO:
    """Pins PersonDTO field defaults and constraints."""

    @pytest.mark.unit
    def test_constructs_with_name_only(self):
        """Name is the only required field; others default."""
        dto = PersonDTO(name="Alice")
        assert dto.name == "Alice"
        assert dto.email is None
        assert dto.role == "member"
        assert dto.expertise is None
        assert dto.proficiency is None

    @pytest.mark.unit
    def test_invalid_role_raises(self):
        """Invalid role literal raises ValidationError."""
        with pytest.raises(ValidationError):
            PersonDTO(name="Alice", role="superadmin")


# ---------------------------------------------------------------------------
# ComputerDTO
# ---------------------------------------------------------------------------


class TestComputerDTO:
    """Pins ComputerDTO required fields and defaults."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """Required fields produce a valid DTO with None defaults."""
        dto = ComputerDTO(name="myhost", status="online", is_local=True)
        assert dto.name == "myhost"
        assert dto.status == "online"
        assert dto.is_local is True
        assert dto.user is None
        assert dto.host is None
        assert dto.tmux_binary is None


# ---------------------------------------------------------------------------
# ProjectDTO
# ---------------------------------------------------------------------------


class TestProjectDTO:
    """Pins ProjectDTO required fields and defaults."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """Required fields produce a valid DTO."""
        dto = ProjectDTO(computer="host", name="myproject", path="/srv/project")
        assert dto.computer == "host"
        assert dto.name == "myproject"
        assert dto.path == "/srv/project"
        assert dto.description is None


# ---------------------------------------------------------------------------
# SetAgentStatusRequest
# ---------------------------------------------------------------------------


class TestSetAgentStatusRequest:
    """Pins SetAgentStatusRequest constraints."""

    @pytest.mark.unit
    def test_valid_status_constructs(self):
        """Valid status literal constructs the request."""
        req = SetAgentStatusRequest(status="available")
        assert req.status == "available"
        assert req.reason is None
        assert req.duration_minutes is None

    @pytest.mark.unit
    def test_invalid_status_raises(self):
        """Invalid status literal raises ValidationError."""
        with pytest.raises(ValidationError):
            SetAgentStatusRequest(status="broken")


# ---------------------------------------------------------------------------
# SessionsInitialDataDTO
# ---------------------------------------------------------------------------


class TestSessionsInitialDataDTO:
    """Pins SessionsInitialDataDTO fields."""

    @pytest.mark.unit
    def test_constructs_with_empty_sessions(self):
        """Constructs with an empty sessions list."""
        dto = SessionsInitialDataDTO(sessions=[])
        assert dto.sessions == []
        assert dto.computer is None


# ---------------------------------------------------------------------------
# SessionsInitialEventDTO
# ---------------------------------------------------------------------------


class TestSessionsInitialEventDTO:
    """Pins SessionsInitialEventDTO event literal and nesting."""

    @pytest.mark.unit
    def test_event_literal_default(self):
        """Event field defaults to 'sessions_initial'."""
        dto = SessionsInitialEventDTO(data=SessionsInitialDataDTO(sessions=[]))
        assert dto.event == "sessions_initial"


# ---------------------------------------------------------------------------
# ProjectsInitialDataDTO
# ---------------------------------------------------------------------------


class TestProjectsInitialDataDTO:
    """Pins ProjectsInitialDataDTO fields."""

    @pytest.mark.unit
    def test_constructs_with_empty_projects(self):
        """Constructs with an empty projects list."""
        dto = ProjectsInitialDataDTO(projects=[])
        assert dto.projects == []
        assert dto.computer is None


# ---------------------------------------------------------------------------
# ProjectsInitialEventDTO
# ---------------------------------------------------------------------------


class TestProjectsInitialEventDTO:
    """Pins ProjectsInitialEventDTO event literal."""

    @pytest.mark.unit
    def test_projects_initial_event(self):
        """Accepts 'projects_initial' literal."""
        dto = ProjectsInitialEventDTO(
            event="projects_initial",
            data=ProjectsInitialDataDTO(projects=[]),
        )
        assert dto.event == "projects_initial"

    @pytest.mark.unit
    def test_preparation_initial_event(self):
        """Accepts 'preparation_initial' literal."""
        dto = ProjectsInitialEventDTO(
            event="preparation_initial",
            data=ProjectsInitialDataDTO(projects=[]),
        )
        assert dto.event == "preparation_initial"


# ---------------------------------------------------------------------------
# SessionStartedEventDTO
# ---------------------------------------------------------------------------


class TestSessionStartedEventDTO:
    """Pins SessionStartedEventDTO event literal and data type."""

    @pytest.mark.unit
    def test_constructs_with_session_dto(self):
        """Wraps a SessionDTO in a session_started event."""
        session = SessionDTO(session_id="s-1", title="Test", status="active")
        dto = SessionStartedEventDTO(event="session_started", data=session)
        assert dto.event == "session_started"
        assert dto.data.session_id == "s-1"


# ---------------------------------------------------------------------------
# SessionUpdatedEventDTO
# ---------------------------------------------------------------------------


class TestSessionUpdatedEventDTO:
    """Pins SessionUpdatedEventDTO event literal."""

    @pytest.mark.unit
    def test_constructs_with_session_dto(self):
        """Wraps a SessionDTO in a session_updated event."""
        session = SessionDTO(session_id="s-2", title="Updated", status="active")
        dto = SessionUpdatedEventDTO(event="session_updated", data=session)
        assert dto.event == "session_updated"
        assert dto.data.session_id == "s-2"


# ---------------------------------------------------------------------------
# SessionClosedDataDTO
# ---------------------------------------------------------------------------


class TestSessionClosedDataDTO:
    """Pins SessionClosedDataDTO fields."""

    @pytest.mark.unit
    def test_constructs_with_session_id(self):
        """Only requires session_id."""
        dto = SessionClosedDataDTO(session_id="s-closed")
        assert dto.session_id == "s-closed"


# ---------------------------------------------------------------------------
# SessionClosedEventDTO
# ---------------------------------------------------------------------------


class TestSessionClosedEventDTO:
    """Pins SessionClosedEventDTO event literal default."""

    @pytest.mark.unit
    def test_event_defaults_to_session_closed(self):
        """Event field defaults to 'session_closed'."""
        dto = SessionClosedEventDTO(data=SessionClosedDataDTO(session_id="s-1"))
        assert dto.event == "session_closed"


# ---------------------------------------------------------------------------
# RefreshDataDTO
# ---------------------------------------------------------------------------


class TestRefreshDataDTO:
    """Pins RefreshDataDTO optional fields."""

    @pytest.mark.unit
    def test_all_fields_optional(self):
        """Constructs with no arguments; all fields None."""
        dto = RefreshDataDTO()
        assert dto.computer is None
        assert dto.project_path is None


# ---------------------------------------------------------------------------
# RefreshEventDTO
# ---------------------------------------------------------------------------


class TestRefreshEventDTO:
    """Pins RefreshEventDTO event literal union."""

    @pytest.mark.unit
    def test_computer_updated_event(self):
        """Accepts 'computer_updated' literal."""
        dto = RefreshEventDTO(event="computer_updated", data=RefreshDataDTO())
        assert dto.event == "computer_updated"

    @pytest.mark.unit
    def test_todos_updated_event(self):
        """Accepts 'todos_updated' literal."""
        dto = RefreshEventDTO(event="todos_updated", data=RefreshDataDTO())
        assert dto.event == "todos_updated"

    @pytest.mark.unit
    def test_invalid_event_raises(self):
        """Unknown event literal raises ValidationError."""
        with pytest.raises(ValidationError):
            RefreshEventDTO(event="unknown_event", data=RefreshDataDTO())


# ---------------------------------------------------------------------------
# ErrorEventDataDTO
# ---------------------------------------------------------------------------


class TestErrorEventDataDTO:
    """Pins ErrorEventDataDTO defaults and constraints."""

    @pytest.mark.unit
    def test_constructs_with_message_only(self):
        """Message is required; other fields have defaults."""
        dto = ErrorEventDataDTO(message="Something failed")
        assert dto.message == "Something failed"
        assert dto.session_id is None
        assert dto.source is None
        assert dto.severity == "error"
        assert dto.retryable is False
        assert dto.code is None

    @pytest.mark.unit
    def test_severity_literal_enforced(self):
        """Invalid severity raises ValidationError."""
        with pytest.raises(ValidationError):
            ErrorEventDataDTO(message="fail", severity="info")


# ---------------------------------------------------------------------------
# ErrorEventDTO
# ---------------------------------------------------------------------------


class TestErrorEventDTO:
    """Pins ErrorEventDTO event literal default."""

    @pytest.mark.unit
    def test_event_defaults_to_error(self):
        """Event field defaults to 'error'."""
        dto = ErrorEventDTO(data=ErrorEventDataDTO(message="oops"))
        assert dto.event == "error"


# ---------------------------------------------------------------------------
# ChiptunesTrackEventDTO
# ---------------------------------------------------------------------------


class TestChiptunesTrackEventDTO:
    """Pins ChiptunesTrackEventDTO defaults."""

    @pytest.mark.unit
    def test_constructs_with_track(self):
        """Track is required; sid_path defaults to empty."""
        dto = ChiptunesTrackEventDTO(track="battle.sid")
        assert dto.event == "chiptunes_track"
        assert dto.track == "battle.sid"
        assert dto.sid_path == ""


# ---------------------------------------------------------------------------
# ChiptunesStateEventDTO
# ---------------------------------------------------------------------------


class TestChiptunesStateEventDTO:
    """Pins ChiptunesStateEventDTO defaults."""

    @pytest.mark.unit
    def test_defaults(self):
        """All fields have sensible defaults matching ChiptunesStatusDTO."""
        dto = ChiptunesStateEventDTO()
        assert dto.event == "chiptunes_state"
        assert dto.playback == "cold"
        assert dto.loaded is False
        assert dto.playing is False
        assert dto.paused is False
        assert dto.position_seconds == 0.0
        assert dto.track == ""
        assert dto.pending_action == ""


# ---------------------------------------------------------------------------
# ChiptunesCommandReceiptDTO
# ---------------------------------------------------------------------------


class TestChiptunesCommandReceiptDTO:
    """Pins ChiptunesCommandReceiptDTO fields."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """command_id and action are required; status defaults to 'accepted'."""
        dto = ChiptunesCommandReceiptDTO(command_id="cmd-1", action="resume")
        assert dto.status == "accepted"
        assert dto.command_id == "cmd-1"
        assert dto.action == "resume"

    @pytest.mark.unit
    def test_invalid_action_raises(self):
        """Invalid action literal raises ValidationError."""
        with pytest.raises(ValidationError):
            ChiptunesCommandReceiptDTO(command_id="cmd-1", action="stop")


# ---------------------------------------------------------------------------
# SessionLifecycleStatusEventDTO
# ---------------------------------------------------------------------------


class TestSessionLifecycleStatusEventDTO:
    """Pins SessionLifecycleStatusEventDTO fields and defaults."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """Required fields produce a valid DTO; optional fields default to None."""
        dto = SessionLifecycleStatusEventDTO(
            session_id="s-1",
            status="active",
            reason="session_started",
            timestamp="2025-01-01T00:00:00Z",
        )
        assert dto.event == "session_status"
        assert dto.session_id == "s-1"
        assert dto.status == "active"
        assert dto.reason == "session_started"
        assert dto.last_activity_at is None
        assert dto.message_intent is None
        assert dto.delivery_scope is None

    @pytest.mark.unit
    def test_exclude_none_omits_optional_fields(self):
        """model_dump(exclude_none=True) omits None optional fields."""
        dto = SessionLifecycleStatusEventDTO(
            session_id="s-1",
            status="active",
            reason="started",
            timestamp="2025-01-01T00:00:00Z",
        )
        dumped = dto.model_dump(exclude_none=True)
        assert "last_activity_at" not in dumped
        assert "message_intent" not in dumped


# ---------------------------------------------------------------------------
# AgentActivityEventDTO
# ---------------------------------------------------------------------------


class TestAgentActivityEventDTO:
    """Pins AgentActivityEventDTO fields and defaults."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """session_id and type are required; optional fields default to None."""
        dto = AgentActivityEventDTO(session_id="s-1", type="tool_use")
        assert dto.event == "agent_activity"
        assert dto.session_id == "s-1"
        assert dto.type == "tool_use"
        assert dto.tool_name is None
        assert dto.tool_preview is None
        assert dto.summary is None
        assert dto.canonical_type is None

    @pytest.mark.unit
    def test_canonical_fields_included(self):
        """Canonical contract fields are stored when provided."""
        dto = AgentActivityEventDTO(
            session_id="s-1",
            type="tool_done",
            canonical_type="agent_output_update",
            message_intent="ctrl_activity",
            delivery_scope="CTRL",
        )
        assert dto.canonical_type == "agent_output_update"
        assert dto.message_intent == "ctrl_activity"
        assert dto.delivery_scope == "CTRL"


# ---------------------------------------------------------------------------
# TTSSettingsDTO
# ---------------------------------------------------------------------------


class TestTTSSettingsDTO:
    """Pins TTSSettingsDTO defaults."""

    @pytest.mark.unit
    def test_enabled_defaults_to_false(self):
        """enabled defaults to False."""
        dto = TTSSettingsDTO()
        assert dto.enabled is False


# ---------------------------------------------------------------------------
# SettingsDTO
# ---------------------------------------------------------------------------


class TestSettingsDTO:
    """Pins SettingsDTO nested structure."""

    @pytest.mark.unit
    def test_constructs_with_tts(self):
        """tts field is required and wraps TTSSettingsDTO."""
        dto = SettingsDTO(tts=TTSSettingsDTO(enabled=True))
        assert dto.tts.enabled is True


# ---------------------------------------------------------------------------
# SessionMessagesDTO
# ---------------------------------------------------------------------------


class TestSessionMessagesDTO:
    """Pins SessionMessagesDTO defaults."""

    @pytest.mark.unit
    def test_constructs_with_session_id(self):
        """session_id is required; messages defaults to empty list."""
        dto = SessionMessagesDTO(session_id="s-1")
        assert dto.session_id == "s-1"
        assert dto.agent is None
        assert dto.messages == []

    @pytest.mark.unit
    def test_messages_accepts_message_dto_list(self):
        """messages field accepts a list of MessageDTO."""
        msg = MessageDTO(role="user", type="text", text="hello")
        dto = SessionMessagesDTO(session_id="s-1", messages=[msg])
        assert len(dto.messages) == 1
        assert dto.messages[0].text == "hello"


# ---------------------------------------------------------------------------
# JobDTO
# ---------------------------------------------------------------------------


class TestJobDTO:
    """Pins JobDTO required fields and constraints."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """Required fields produce a valid DTO."""
        dto = JobDTO(name="cleanup", type="script", status="idle")
        assert dto.name == "cleanup"
        assert dto.type == "script"
        assert dto.status == "idle"
        assert dto.schedule is None
        assert dto.last_run is None

    @pytest.mark.unit
    def test_invalid_type_raises(self):
        """Invalid type literal raises ValidationError."""
        with pytest.raises(ValidationError):
            JobDTO(name="cleanup", type="cron", status="idle")


# ---------------------------------------------------------------------------
# SendResultRequest
# ---------------------------------------------------------------------------


class TestSendResultRequest:
    """Pins SendResultRequest constraints and defaults."""

    @pytest.mark.unit
    def test_constructs_with_content(self):
        """content is required; output_format defaults to 'markdown'."""
        req = SendResultRequest(content="Result text")
        assert req.content == "Result text"
        assert req.output_format == "markdown"

    @pytest.mark.unit
    def test_content_min_length_enforced(self):
        """Empty content raises ValidationError."""
        with pytest.raises(ValidationError):
            SendResultRequest(content="")

    @pytest.mark.unit
    def test_output_format_literal_enforced(self):
        """Invalid output_format raises ValidationError."""
        with pytest.raises(ValidationError):
            SendResultRequest(content="Result", output_format="plaintext")


# ---------------------------------------------------------------------------
# RenderWidgetRequest
# ---------------------------------------------------------------------------


class TestRenderWidgetRequest:
    """Pins RenderWidgetRequest fields."""

    @pytest.mark.unit
    def test_constructs_with_data(self):
        """data dict is required."""
        req = RenderWidgetRequest(data={"type": "chart", "values": [1, 2, 3]})
        assert req.data["type"] == "chart"


# ---------------------------------------------------------------------------
# EscalateRequest
# ---------------------------------------------------------------------------


class TestEscalateRequest:
    """Pins EscalateRequest constraints and defaults."""

    @pytest.mark.unit
    def test_constructs_with_required_fields(self):
        """customer_name and reason are required; context_summary is optional."""
        req = EscalateRequest(customer_name="Acme Corp", reason="Billing issue")
        assert req.customer_name == "Acme Corp"
        assert req.reason == "Billing issue"
        assert req.context_summary is None

    @pytest.mark.unit
    def test_customer_name_min_length_enforced(self):
        """Empty customer_name raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalateRequest(customer_name="", reason="Billing issue")

    @pytest.mark.unit
    def test_reason_min_length_enforced(self):
        """Empty reason raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalateRequest(customer_name="Acme Corp", reason="")


# ---------------------------------------------------------------------------
# AgentStatusRequest
# ---------------------------------------------------------------------------


class TestAgentStatusRequest:
    """Pins AgentStatusRequest constraints and defaults."""

    @pytest.mark.unit
    def test_constructs_with_defaults(self):
        """All fields are optional with None defaults except clear."""
        req = AgentStatusRequest()
        assert req.status is None
        assert req.reason is None
        assert req.duration_minutes is None
        assert req.unavailable_until is None
        assert req.clear is False

    @pytest.mark.unit
    def test_invalid_status_raises(self):
        """Invalid status literal raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentStatusRequest(status="broken")

    @pytest.mark.unit
    def test_clear_flag_accepted(self):
        """clear=True is valid without other fields."""
        req = AgentStatusRequest(clear=True)
        assert req.clear is True


# ---------------------------------------------------------------------------
# OperationStatusPayload (TypedDict)
# ---------------------------------------------------------------------------


class TestOperationStatusPayload:
    """Pins OperationStatusPayload as a valid TypedDict."""

    @pytest.mark.unit
    def test_required_keys_present(self):
        """TypedDict accepts the required key set."""
        payload: OperationStatusPayload = {
            "operation_id": "op-1",
            "kind": "session_start",
            "state": "running",
            "poll_after_ms": 0,
            "status_path": "/tmp/op-1",
            "recovery_command": "telec operations get op-1",
        }
        assert payload["operation_id"] == "op-1"
        assert payload["state"] == "running"

    @pytest.mark.unit
    def test_optional_keys_accepted(self):
        """TypedDict accepts NotRequired keys."""
        payload: OperationStatusPayload = {
            "operation_id": "op-1",
            "kind": "session_start",
            "state": "completed",
            "poll_after_ms": 0,
            "status_path": "/tmp/op-1",
            "recovery_command": "telec operations get op-1",
            "slug": "my-slug",
            "result": "done",
        }
        assert payload["slug"] == "my-slug"
        assert payload["result"] == "done"
