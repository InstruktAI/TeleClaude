"""Internal command models for TeleClaude."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
from typing import Optional, TypedDict, cast
from uuid import uuid4

from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import EndpointStamp, SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._types import JsonDict, JsonValue
from teleclaude.docs_subscriptions import EventDeliveryMode, SubscriptionAttendance, SubscriptionIdentity
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.media import MediaRef
from teleclaude.types.procedure_delivery import ProcedureSessionDeliveryInitialization

_RUNTIME_RUN_ID_FIELD = "runtime_run_id"


class CommandType(str, Enum):
    """Internal command types."""

    CREATE_SESSION = "create_session"
    HANDLE_VOICE = "handle_voice"
    HANDLE_FILE = "handle_file"
    KEYS = "keys"
    START_AGENT = "start_agent"
    RESUME_AGENT = "resume_agent"
    PROCESS_MESSAGE = "process_message"
    RUN_AGENT_COMMAND = "run_agent_command"
    RESTART_AGENT = "restart_agent"
    HANDOFF_AGENT = "handoff_agent"
    REVIVE_AGENT = "revive_agent"
    UNSUBSCRIBE_SESSION = "unsubscribe_session"
    GET_SESSION_DATA = "get_session_data"
    CLOSE_SESSION = "close_session"
    SYSTEM = "system_command"
    SET_VOICE_FOCUS = "set_voice_focus"
    ACTIVATE_PROCEDURE = "activate_procedure"
    RELAY_REQUEST = "relay_request"


class ResponseMode(str, Enum):
    """Declares how the API/dispatch layer handles a command's response."""

    IMMEDIATE = "immediate"
    RECEIPT = "receipt"


@dataclass(frozen=True, kw_only=True)
class CallerProvenance:
    """Identity of the session that submitted a command, resolved at the API boundary.

    Carried on every command's ``caller`` field so an owning computer that
    receives a forwarded command can reconstruct the same caller the
    originating computer resolved, without a per-command special case.
    """

    session_id: str
    author_kind: str
    author_display: str
    computer: str | None = None
    agent_runtime: str | None = None
    thinking_mode: str | None = None
    machine_role: str | None = None
    job_role: str | None = None

    def to_dict(self) -> JsonDict:
        """Serialize as the nested ``caller`` block of a command's wire payload."""
        return {
            "session_id": self.session_id,
            "author_kind": self.author_kind,
            "author_display": self.author_display,
            "computer": self.computer,
            "agent_runtime": self.agent_runtime,
            "thinking_mode": self.thinking_mode,
            "machine_role": self.machine_role,
            "job_role": self.job_role,
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> "CallerProvenance":
        """Rebuild from the nested ``caller`` block of a command's wire payload."""
        return CallerProvenance(
            session_id=cast(str, data["session_id"]),
            author_kind=cast(str, data["author_kind"]),
            author_display=cast(str, data["author_display"]),
            computer=cast("str | None", data.get("computer")),
            agent_runtime=cast("str | None", data.get("agent_runtime")),
            thinking_mode=cast("str | None", data.get("thinking_mode")),
            machine_role=cast("str | None", data.get("machine_role")),
            job_role=cast("str | None", data.get("job_role")),
        )


class RestartAgentResult(TypedDict):
    """Immediate outcome of a restart request that resolves a successor."""

    ok: bool
    error: str | None
    selected_agent: str | None


@dataclass(kw_only=True)
class InternalCommand:
    """Base class for all internal commands."""

    command_type: CommandType
    computer: str | None = None
    request_id: str | None = None
    response_mode: ResponseMode = ResponseMode.IMMEDIATE
    success_event: str | None = None
    failure_event: str | None = None
    caller: CallerProvenance | None = None
    relayed_principal: str | None = None

    def __post_init__(self) -> None:
        declares_events = self.success_event is not None or self.failure_event is not None
        is_receipt = self.response_mode is ResponseMode.RECEIPT
        if declares_events != is_receipt:
            raise ValueError(
                f"{type(self).__name__}: RECEIPT requires both success_event and failure_event, "
                f"and IMMEDIATE declares neither"
            )
        if is_receipt and (self.success_event is None or self.failure_event is None):
            raise ValueError(f"{type(self).__name__}: RECEIPT requires both success_event and failure_event")

    def to_payload(self) -> dict[str, object]:
        """Return payload dict for adapter event dispatch."""
        return {}

    def to_dict(self) -> JsonDict:
        """Serialize a command as the cross-computer wire payload."""
        payload: JsonDict = {}
        for command_field in fields(self):
            name = command_field.name
            value = getattr(self, name)
            if value is None:
                payload[name] = None
            elif isinstance(value, CommandType | ResponseMode):
                payload[name] = value.value
            elif name == "launch_intent":
                payload[name] = cast("SessionLaunchIntent", value).to_dict()
            elif isinstance(value, ProcedureSessionDeliveryInitialization):
                payload[name] = value.to_dict()
            elif isinstance(value, CallerProvenance | EndpointStamp | MediaRef):
                payload[name] = value.to_dict()
            elif isinstance(value, Mapping):
                payload[name] = _json_dict(value)
            elif isinstance(value, list):
                payload[name] = [_json_value(item) for item in value]
            else:
                payload[name] = _json_value(value)
        return payload


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        return _json_dict(value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    raise TypeError(f"Command field is not JSON serializable: {type(value).__name__}")


def _json_dict(value: Mapping[str, object]) -> JsonDict:
    return {str(key): _json_value(item) for key, item in value.items()}


@dataclass(kw_only=True)
class CreateSessionCommand(InternalCommand):
    """Intent to create a new session."""

    command_type: CommandType = field(init=False, default=CommandType.CREATE_SESSION)
    project_path: str
    origin: str
    session_id: str | None = None
    initial_input: str | None = None
    title: str | None = None
    subdir: str | None = None
    headless: bool = False
    native_session_id: str | None = None
    native_log_file: str | None = None
    human_email: str | None = None
    human_role: str | None = None
    initiator_session_id: str | None = None
    initiator_computer: str | None = None
    startup_work_expected: bool = False
    skip_listener_registration: bool = False
    origin_metadata: Mapping[str, object] | None = None
    launch_intent: Optional["SessionLaunchIntent"] = None
    role: str | None = None
    job: str | None = None
    company: str | None = None
    command: str | None = None
    working_slug: str | None = None
    entry_point: SessionEntryPoint | None = None
    command_input_mode: CommandInputMode = CommandInputMode.ORDINARY
    command_input_source_text: str | None = None
    endpoint: EndpointStamp | None = None
    unattended: bool = False
    procedure_delivery: ProcedureSessionDeliveryInitialization | None = None
    # Daemon-internal: the session runs under the computer's operator principal. No request maps onto it.
    operator: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.request_id is None:
            self.request_id = str(uuid4())
        if self.procedure_delivery is not None and self.entry_point is not SessionEntryPoint.PROCEDURE_ACTIVATION:
            raise ValueError("procedure delivery initialization requires a procedure activation session")

    def to_payload(self) -> dict[str, object]:
        args: list[str] = [self.initial_input] if self.initial_input else []
        return {"session_id": "", "args": args}


@dataclass(kw_only=True)
class StartAgentCommand(InternalCommand):
    """Intent to start an agent in an existing session."""

    session_id: str
    agent_name: str
    thinking_mode: str = "slow"
    args: list[str] = field(default_factory=list)
    origin: str | None = None
    runtime_run_id: str | None = None
    resolved_model_flags: str | None = None
    visible_input_source_text: str | None = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        thinking_mode: str = "slow",
        args: list[str] | None = None,
        origin: str | None = None,
        runtime_run_id: str | None = None,
        resolved_model_flags: str | None = None,
        visible_input_source_text: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.START_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.thinking_mode = thinking_mode
        self.args = args or []
        self.origin = origin
        self.runtime_run_id = runtime_run_id
        self.resolved_model_flags = resolved_model_flags
        self.visible_input_source_text = visible_input_source_text

    def to_payload(self) -> dict[str, object]:
        args = [self.agent_name] + list(self.args)
        return {"session_id": self.session_id, "args": args}

    def to_dict(self) -> JsonDict:
        """Serialize durable start intent without local model-resolution state."""
        payload = super().to_dict()
        payload.pop("resolved_model_flags", None)
        payload.pop(_RUNTIME_RUN_ID_FIELD, None)
        return payload


@dataclass(kw_only=True)
class ResumeAgentCommand(InternalCommand):
    """Intent to resume an agent in an existing session."""

    session_id: str
    agent_name: str | None = None
    native_session_id: str | None = None
    origin: str | None = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str | None = None,
        native_session_id: str | None = None,
        origin: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.RESUME_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.native_session_id = native_session_id
        self.origin = origin

    def to_payload(self) -> dict[str, object]:
        args: list[str] = []
        if self.agent_name:
            args.append(self.agent_name)
        if self.native_session_id:
            args.append(self.native_session_id)
        return {"session_id": self.session_id, "args": args}


# Payload key for the durable source-occurrence receipt carried by
# ProcessMessageCommand. Session-originated sends mint a value at the API
# ingress so identity-content is constructible with its required receipt key.
OCCURRENCE_KEY = "occurrence_key"

_ORIGIN_PAYLOAD_KEY = "origin"
_ACTOR_ID_PAYLOAD_KEY = "actor_id"
_SOURCE_MESSAGE_ID_PAYLOAD_KEY = "source_message_id"


@dataclass(kw_only=True)
class ProcessMessageCommand(InternalCommand):
    """Intent to process an incoming user message for a session."""

    session_id: str
    text: str
    origin: str
    text_kind: TranscriptEntryKind
    source_feature: InjectedTextSourceFeature
    occurrence_key: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    source_message_id: str | None = None  # Platform message ID for inbound dedup
    source_channel_id: str | None = None  # Platform channel ID for additional context
    origin_metadata: Mapping[str, object] | None = None
    # `caller_origin_prefix_len`/`caller_origin_suffix_len` describe envelope
    # trimming of the message body — message-projection fields, not caller
    # identity. The caller's resolved event author lives on the base class's
    # `caller` field (see the properties below) for a session-originated send
    # (e.g. plain `telec sessions send`); absent for ordinary human/adapter-
    # originated input.
    caller_origin_prefix_len: int | None = None
    caller_origin_suffix_len: int | None = None
    command_input_mode: CommandInputMode = CommandInputMode.ORDINARY
    sender_human_role: str | None = None
    # Set when a channel recovered this input after the platform was offline: the time it was originally posted.
    recovered_posted_at: datetime | None = None

    def __init__(
        self,
        *,
        session_id: str,
        text: str,
        origin: str,
        text_kind: TranscriptEntryKind,
        source_feature: InjectedTextSourceFeature,
        occurrence_key: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        request_id: str | None = None,
        source_message_id: str | None = None,
        source_channel_id: str | None = None,
        origin_metadata: Mapping[str, object] | None = None,
        caller_session_id: str | None = None,
        caller_author_kind: str | None = None,
        caller_author_display: str | None = None,
        caller_agent_runtime: str | None = None,
        caller_thinking_mode: str | None = None,
        caller_machine_role: str | None = None,
        caller_job_role: str | None = None,
        caller_origin_prefix_len: int | None = None,
        caller_origin_suffix_len: int | None = None,
        command_input_mode: CommandInputMode = CommandInputMode.ORDINARY,
        sender_human_role: str | None = None,
        recovered_posted_at: datetime | None = None,
    ):
        super().__init__(command_type=CommandType.PROCESS_MESSAGE, request_id=request_id)
        self.session_id = session_id
        self.text = text
        self.origin = origin
        self.text_kind = text_kind
        self.source_feature = source_feature
        self.occurrence_key = occurrence_key
        self.actor_id = actor_id
        self.actor_name = actor_name
        self.actor_avatar_url = actor_avatar_url
        self.source_message_id = source_message_id
        self.source_channel_id = source_channel_id
        self.origin_metadata = origin_metadata
        self.caller = (
            CallerProvenance(
                session_id=caller_session_id,
                author_kind=caller_author_kind,
                author_display=caller_author_display,
                agent_runtime=caller_agent_runtime,
                thinking_mode=caller_thinking_mode,
                machine_role=caller_machine_role,
                job_role=caller_job_role,
            )
            if caller_session_id and caller_author_kind and caller_author_display
            else None
        )
        self.caller_origin_prefix_len = caller_origin_prefix_len
        self.caller_origin_suffix_len = caller_origin_suffix_len
        self.command_input_mode = command_input_mode
        self.sender_human_role = sender_human_role
        self.recovered_posted_at = recovered_posted_at

    @property
    def caller_session_id(self) -> str | None:
        return self.caller.session_id if self.caller else None

    @property
    def caller_author_kind(self) -> str | None:
        return self.caller.author_kind if self.caller else None

    @property
    def caller_author_display(self) -> str | None:
        return self.caller.author_display if self.caller else None

    @property
    def caller_agent_runtime(self) -> str | None:
        return self.caller.agent_runtime if self.caller else None

    @property
    def caller_thinking_mode(self) -> str | None:
        return self.caller.thinking_mode if self.caller else None

    @property
    def caller_machine_role(self) -> str | None:
        return self.caller.machine_role if self.caller else None

    @property
    def caller_job_role(self) -> str | None:
        return self.caller.job_role if self.caller else None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "text": self.text,
            "origin": self.origin,
            "text_kind": self.text_kind.value,
            "source_feature": self.source_feature.value,
        }
        if self.occurrence_key is not None:
            payload[OCCURRENCE_KEY] = self.occurrence_key
        if self.actor_id is not None:
            payload["actor_id"] = self.actor_id
        if self.actor_name is not None:
            payload["actor_name"] = self.actor_name
        if self.actor_avatar_url is not None:
            payload["actor_avatar_url"] = self.actor_avatar_url
        if self.source_message_id is not None:
            payload["source_message_id"] = self.source_message_id
        if self.source_channel_id is not None:
            payload["source_channel_id"] = self.source_channel_id
        if self.origin_metadata is not None:
            payload["origin_metadata"] = dict(self.origin_metadata)
        if self.caller_session_id is not None:
            payload["caller_session_id"] = self.caller_session_id
        if self.caller_author_kind is not None:
            payload["caller_author_kind"] = self.caller_author_kind
        if self.caller_author_display is not None:
            payload["caller_author_display"] = self.caller_author_display
        if self.caller_agent_runtime is not None:
            payload["caller_agent_runtime"] = self.caller_agent_runtime
        if self.caller_thinking_mode is not None:
            payload["caller_thinking_mode"] = self.caller_thinking_mode
        if self.caller_machine_role is not None:
            payload["caller_machine_role"] = self.caller_machine_role
        if self.caller_job_role is not None:
            payload["caller_job_role"] = self.caller_job_role
        if self.caller_origin_prefix_len is not None:
            payload["caller_origin_prefix_len"] = self.caller_origin_prefix_len
        if self.caller_origin_suffix_len is not None:
            payload["caller_origin_suffix_len"] = self.caller_origin_suffix_len
        return payload


@dataclass(kw_only=True)
class HandleVoiceCommand(InternalCommand):
    """Intent to handle a voice input for a session."""

    session_id: str
    file_path: str
    duration: float | None = None
    message_id: str | None = None
    message_thread_id: int | None = None
    origin: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    origin_metadata: Mapping[str, object] | None = None
    voice_transcription_id: int | None = None
    notice_message_id: str | None = None
    media_ref: MediaRef | None = None
    source_message_id: str | None = None
    recovered_posted_at: datetime | None = None

    def __init__(
        self,
        *,
        session_id: str,
        file_path: str,
        duration: float | None = None,
        message_id: str | None = None,
        message_thread_id: int | None = None,
        origin: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        origin_metadata: Mapping[str, object] | None = None,
        voice_transcription_id: int | None = None,
        notice_message_id: str | None = None,
        media_ref: MediaRef | None = None,
        source_message_id: str | None = None,
        recovered_posted_at: datetime | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.HANDLE_VOICE, request_id=request_id)
        self.session_id = session_id
        self.file_path = file_path
        self.duration = duration
        self.message_id = message_id
        self.message_thread_id = message_thread_id
        self.origin = origin
        self.actor_id = actor_id
        self.actor_name = actor_name
        self.actor_avatar_url = actor_avatar_url
        self.origin_metadata = origin_metadata
        self.voice_transcription_id = voice_transcription_id
        self.notice_message_id = notice_message_id
        self.media_ref = media_ref
        self.source_message_id = source_message_id
        self.recovered_posted_at = recovered_posted_at

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "file_path": self.file_path,
        }
        if self.duration is not None:
            payload["duration"] = self.duration
        if self.message_id is not None:
            payload["message_id"] = self.message_id
        if self.message_thread_id is not None:
            payload["message_thread_id"] = self.message_thread_id
        if self.origin is not None:
            payload["origin"] = self.origin
        if self.actor_id is not None:
            payload["actor_id"] = self.actor_id
        if self.actor_name is not None:
            payload["actor_name"] = self.actor_name
        if self.actor_avatar_url is not None:
            payload["actor_avatar_url"] = self.actor_avatar_url
        if self.origin_metadata is not None:
            payload["origin_metadata"] = dict(self.origin_metadata)
        if self.voice_transcription_id is not None:
            payload["voice_transcription_id"] = self.voice_transcription_id
        if self.notice_message_id is not None:
            payload["notice_message_id"] = self.notice_message_id
        if self.source_message_id is not None:
            payload[_SOURCE_MESSAGE_ID_PAYLOAD_KEY] = self.source_message_id
        return payload


@dataclass(kw_only=True)
class HandleFileCommand(InternalCommand):
    """Intent to handle a file upload for a session."""

    session_id: str
    file_path: str
    filename: str
    caption: str | None = None
    file_size: int = 0
    media_ref: MediaRef | None = None
    origin: str | None = None
    actor_id: str | None = None
    source_message_id: str | None = None
    recovered_posted_at: datetime | None = None

    def __init__(
        self,
        *,
        session_id: str,
        file_path: str,
        filename: str,
        caption: str | None = None,
        file_size: int = 0,
        media_ref: MediaRef | None = None,
        origin: str | None = None,
        actor_id: str | None = None,
        source_message_id: str | None = None,
        recovered_posted_at: datetime | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.HANDLE_FILE, request_id=request_id)
        self.session_id = session_id
        self.file_path = file_path
        self.filename = filename
        self.caption = caption
        self.file_size = file_size
        self.media_ref = media_ref
        self.origin = origin
        self.actor_id = actor_id
        self.source_message_id = source_message_id
        self.recovered_posted_at = recovered_posted_at

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "file_path": self.file_path,
            "filename": self.filename,
            "file_size": self.file_size,
        }
        if self.caption is not None:
            payload["caption"] = self.caption
        if self.origin is not None:
            payload[_ORIGIN_PAYLOAD_KEY] = self.origin
        if self.actor_id is not None:
            payload[_ACTOR_ID_PAYLOAD_KEY] = self.actor_id
        if self.source_message_id is not None:
            payload[_SOURCE_MESSAGE_ID_PAYLOAD_KEY] = self.source_message_id
        return payload


@dataclass(kw_only=True)
class KeysCommand(InternalCommand):
    """Intent to send key/control commands to a session."""

    session_id: str
    key: str
    args: list[str] = field(default_factory=list)

    def __init__(
        self,
        *,
        session_id: str,
        key: str,
        args: list[str] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.KEYS, request_id=request_id)
        self.session_id = session_id
        self.key = key
        self.args = args or []

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "args": list(self.args)}


@dataclass(kw_only=True)
class RunAgentCommand(InternalCommand):
    """Intent to run a slash command inside an agent session."""

    session_id: str
    command: str
    args: str = ""
    origin: str

    def __init__(
        self,
        *,
        session_id: str,
        command: str,
        args: str = "",
        origin: str,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.RUN_AGENT_COMMAND, request_id=request_id)
        self.session_id = session_id
        self.command = command
        self.args = args
        self.origin = origin

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "command": self.command, "args": self.args, "origin": self.origin}


@dataclass(kw_only=True)
class RestartAgentCommand(InternalCommand):
    """Intent to restart an agent in the session."""

    session_id: str
    self_restart: bool = False

    def __init__(
        self,
        *,
        session_id: str,
        self_restart: bool = False,
        request_id: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.RESTART_AGENT,
            request_id=request_id,
            response_mode=ResponseMode.RECEIPT,
            success_event="agent.restart.completed",
            failure_event="agent.restart.failed",
        )
        self.session_id = session_id
        self.self_restart = self_restart

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "args": []}


@dataclass(kw_only=True)
class ReviveAgentCommand(InternalCommand):
    """Intent to revive a session's agent, reporting session id, host-pane reference and agent synchronously.

    A separate command type from ``RestartAgentCommand`` — sharing its handler
    body but declaring ``IMMEDIATE``, because revival's response contract is
    synchronous by design (``session-revival`` UC-SR9), while restart's is
    asynchronous. One class carrying two response modes is what forced a
    post-construction mutation of ``response_mode`` in the first place.
    """

    session_id: str
    self_restart: bool = False

    def __init__(
        self,
        *,
        session_id: str,
        self_restart: bool = False,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.REVIVE_AGENT, request_id=request_id)
        self.session_id = session_id
        self.self_restart = self_restart

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "args": []}


@dataclass(kw_only=True)
class HandoffAgentCommand(InternalCommand):
    """Intent to replace a running agent CLI without changing its TeleClaude session."""

    session_id: str
    agent_name: str | None = None
    caller_role: str | None = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str | None = None,
        caller_role: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.HANDOFF_AGENT,
            request_id=request_id,
            response_mode=ResponseMode.RECEIPT,
            success_event="agent_runtime.handoff.completed",
            failure_event="agent_runtime.handoff.failed",
        )
        self.session_id = session_id
        self.agent_name = agent_name
        self.caller_role = caller_role

    def to_payload(self) -> dict[str, object]:
        args = [self.agent_name] if self.agent_name else []
        return {"session_id": self.session_id, "args": args}


@dataclass(kw_only=True)
class ActivateProcedureCommand(InternalCommand):
    """Intent to wake or start a procedure's agent for the activation home named by a token.

    ``identity`` is which agent answers the event: the home's one agent, or the
    agent of the event's subject within the home. ``attendance`` is whether
    people look at that agent's session.
    """

    procedure_id: str
    home: str
    event_json: str
    identity: SubscriptionIdentity
    attendance: SubscriptionAttendance
    event_delivery: EventDeliveryMode
    interruptible: bool

    def __init__(
        self,
        *,
        procedure_id: str,
        home: str,
        event_json: str,
        identity: SubscriptionIdentity = SubscriptionIdentity.HOME,
        attendance: SubscriptionAttendance = SubscriptionAttendance.ATTENDED,
        event_delivery: EventDeliveryMode = EventDeliveryMode.SEQUENTIAL,
        interruptible: bool = False,
        request_id: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.ACTIVATE_PROCEDURE,
            request_id=request_id,
            response_mode=ResponseMode.RECEIPT,
            success_event="agent_runtime.procedure_activation.completed",
            failure_event="agent_runtime.procedure_activation.failed",
        )
        self.procedure_id = procedure_id
        self.home = ActivationHome.from_token(home).to_token()
        self.event_json = event_json
        self.identity = identity
        self.attendance = attendance
        self.event_delivery = event_delivery
        self.interruptible = interruptible

    def to_payload(self) -> dict[str, object]:
        return {"session_id": "", "args": [self.procedure_id, self.home]}


@dataclass(kw_only=True)
class GetSessionDataCommand(InternalCommand):
    """Intent to fetch session transcript data."""

    session_id: str
    since_timestamp: str | None = None
    until_timestamp: str | None = None
    tail_chars: int = 5000

    def __init__(
        self,
        *,
        session_id: str,
        since_timestamp: str | None = None,
        until_timestamp: str | None = None,
        tail_chars: int = 5000,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.GET_SESSION_DATA, request_id=request_id)
        self.session_id = session_id
        self.since_timestamp = since_timestamp
        self.until_timestamp = until_timestamp
        self.tail_chars = tail_chars

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"session_id": self.session_id}
        if self.since_timestamp is not None:
            payload["since_timestamp"] = self.since_timestamp
        if self.until_timestamp is not None:
            payload["until_timestamp"] = self.until_timestamp
        payload["tail_chars"] = self.tail_chars
        return payload


@dataclass(kw_only=True)
class UnsubscribeSessionCommand(InternalCommand):
    """Intent to remove listener and direct-link interest in a session."""

    command_type: CommandType = field(init=False, default=CommandType.UNSUBSCRIBE_SESSION)
    session_id: str
    caller_session_id: str | None

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "caller_session_id": self.caller_session_id}


@dataclass(kw_only=True)
class CloseSessionCommand(InternalCommand):
    """Intent to close a session."""

    session_id: str

    def __init__(
        self,
        *,
        session_id: str,
        request_id: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.CLOSE_SESSION,
            request_id=request_id,
            response_mode=ResponseMode.RECEIPT,
            success_event="session.close.completed",
            failure_event="session.close.failed",
        )
        self.session_id = session_id

    def to_payload(self) -> dict[str, object]:
        return {"session_id": self.session_id, "args": []}


@dataclass(kw_only=True)
class SystemCommand(InternalCommand):
    """Intent to perform a system-level operation (list sessions, list projects, etc.)."""

    command: str
    args: list[str] = field(default_factory=list)
    data: dict[str, object] | None = None
    session_id: str | None = None

    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        data: dict[str, object] | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        response_mode: ResponseMode = ResponseMode.IMMEDIATE,
        success_event: str | None = None,
        failure_event: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.SYSTEM,
            request_id=request_id,
            response_mode=response_mode,
            success_event=success_event,
            failure_event=failure_event,
        )
        self.command = command
        self.args = args or []
        self.data = data
        self.session_id = session_id

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"command": self.command, "args": self.args}
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.data is not None:
            payload["data"] = self.data
            if "from_computer" in self.data:
                payload["from_computer"] = self.data["from_computer"]
        return payload


@dataclass(kw_only=True)
class SetVoiceFocusCommand(InternalCommand):
    """Intent to durably override a person's voice focus to one session.

    Cross-computer envelope for the "Listen here" control and any other
    explicit-selection surface; the focus record lives on the master.
    """

    command_type: CommandType = field(init=False, default=CommandType.SET_VOICE_FOCUS)
    person_slug: str
    session_id: str

    def to_payload(self) -> dict[str, object]:
        return {"person_slug": self.person_slug, "session_id": self.session_id}


@dataclass(kw_only=True)
class RelayRequestCommand(InternalCommand):
    """One API request carried whole to the computer that owns the object it addresses.

    The owning computer runs the request against its own API, as the caller its
    own registries resolve from the relayed principal, and answers with that
    request's complete response. The command carries no role, scope, author
    kind or runtime of the caller: only the caller session's address, so the
    owner can record who asked and wake it with an outcome.
    """

    command_type: CommandType = field(init=False, default=CommandType.RELAY_REQUEST)
    method: str
    path: str
    deadline_at: float
    query: list[list[str]] = field(default_factory=list)
    body_b64: str = ""
    content_type: str | None = None
    caller_session_id: str | None = None
    caller_computer: str | None = None
    cleared_command: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {"method": self.method, "path": self.path}
