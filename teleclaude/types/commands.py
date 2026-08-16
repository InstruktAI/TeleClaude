"""Internal command models for TeleClaude."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import Enum
from inspect import signature
from typing import Any, Optional, cast
from uuid import uuid4

from teleclaude.core.models import SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._types import JsonDict, JsonValue, PeerBundleSegmentWireDict


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
    UNSUBSCRIBE_SESSION = "unsubscribe_session"
    GET_SESSION_DATA = "get_session_data"
    CLOSE_SESSION = "close_session"
    SYSTEM = "system_command"


class ResponseMode(str, Enum):
    """Declares how the API/dispatch layer handles a command's response."""

    IMMEDIATE = "immediate"
    FIRE_AND_FORGET = "fire_and_forget"
    RECEIPT = "receipt"


@dataclass(kw_only=True)
class InternalCommand:
    """Base class for all internal commands."""

    command_type: CommandType
    computer: str | None = None
    request_id: str | None = None
    response_mode: ResponseMode = ResponseMode.IMMEDIATE
    completion_event: str | None = None

    def __post_init__(self) -> None:
        if self.response_mode == ResponseMode.FIRE_AND_FORGET and self.completion_event is None:
            raise ValueError(
                f"FIRE_AND_FORGET commands must declare a completion_event, "
                f"but {type(self).__name__} has completion_event=None"
            )

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
    skip_listener_registration: bool = False
    origin_metadata: Mapping[str, object] | None = None
    launch_intent: Optional["SessionLaunchIntent"] = None
    system_role: str | None = None
    job: str | None = None
    working_slug: str | None = None
    entry_point: SessionEntryPoint | None = None
    producer_agent: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.request_id is None:
            self.request_id = str(uuid4())

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

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        thinking_mode: str = "slow",
        args: list[str] | None = None,
        origin: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.START_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.thinking_mode = thinking_mode
        self.args = args or []
        self.origin = origin

    def to_payload(self) -> dict[str, object]:
        args = [self.agent_name] + list(self.args)
        return {"session_id": self.session_id, "args": args}


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


@dataclass(kw_only=True)
class ProcessMessageCommand(InternalCommand):
    """Intent to process an incoming user message for a session."""

    session_id: str
    text: str
    origin: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    source_message_id: str | None = None  # Platform message ID for inbound dedup
    source_channel_id: str | None = None  # Platform channel ID for additional context
    origin_metadata: Mapping[str, object] | None = None
    # Structural caller-session provenance for a session-originated send
    # (e.g. plain `telec sessions send`): the caller's resolved event author,
    # carried as a typed value the whole way to the accepted row. Absent for
    # ordinary human/adapter-originated input.
    caller_session_id: str | None = None
    caller_author_kind: str | None = None
    caller_author_display: str | None = None
    caller_agent_runtime: str | None = None
    caller_thinking_mode: str | None = None
    caller_machine_role: str | None = None
    caller_job_role: str | None = None
    caller_origin_prefix_len: int | None = None
    # Structural peer-bundle provenance for a cross-computer peer delivery
    # (`conversation_delivery.py`'s `_deliver_bundle`, cross-computer branch):
    # the durable bundle identity plus its ordered segments, carried across
    # the wire so the receiving computer can persist the SAME structural
    # record its same-computer counterpart already writes directly into the
    # shared local DB. Absent for every other ProcessMessageCommand use.
    peer_bundle_key: str | None = None
    peer_bundle_link_id: str | None = None
    peer_bundle_source_session_id: str | None = None
    peer_bundle_segments: list[PeerBundleSegmentWireDict] | None = None

    def __init__(
        self,
        *,
        session_id: str,
        text: str,
        origin: str,
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
        peer_bundle_key: str | None = None,
        peer_bundle_link_id: str | None = None,
        peer_bundle_source_session_id: str | None = None,
        peer_bundle_segments: list[PeerBundleSegmentWireDict] | None = None,
    ):
        super().__init__(command_type=CommandType.PROCESS_MESSAGE, request_id=request_id)
        self.session_id = session_id
        self.text = text
        self.origin = origin
        self.actor_id = actor_id
        self.actor_name = actor_name
        self.actor_avatar_url = actor_avatar_url
        self.source_message_id = source_message_id
        self.source_channel_id = source_channel_id
        self.origin_metadata = origin_metadata
        self.caller_session_id = caller_session_id
        self.caller_author_kind = caller_author_kind
        self.caller_author_display = caller_author_display
        self.caller_agent_runtime = caller_agent_runtime
        self.caller_thinking_mode = caller_thinking_mode
        self.caller_machine_role = caller_machine_role
        self.caller_job_role = caller_job_role
        self.caller_origin_prefix_len = caller_origin_prefix_len
        self.peer_bundle_key = peer_bundle_key
        self.peer_bundle_link_id = peer_bundle_link_id
        self.peer_bundle_source_session_id = peer_bundle_source_session_id
        self.peer_bundle_segments = peer_bundle_segments

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"session_id": self.session_id, "text": self.text, "origin": self.origin}
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
        return payload


@dataclass(kw_only=True)
class HandleFileCommand(InternalCommand):
    """Intent to handle a file upload for a session."""

    session_id: str
    file_path: str
    filename: str
    caption: str | None = None
    file_size: int = 0

    def __init__(
        self,
        *,
        session_id: str,
        file_path: str,
        filename: str,
        caption: str | None = None,
        file_size: int = 0,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.HANDLE_FILE, request_id=request_id)
        self.session_id = session_id
        self.file_path = file_path
        self.filename = filename
        self.caption = caption
        self.file_size = file_size

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "session_id": self.session_id,
            "file_path": self.file_path,
            "filename": self.filename,
            "file_size": self.file_size,
        }
        if self.caption is not None:
            payload["caption"] = self.caption
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
    agent_name: str | None = None
    self_restart: bool = False

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str | None = None,
        self_restart: bool = False,
        request_id: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.RESTART_AGENT,
            request_id=request_id,
            response_mode=ResponseMode.FIRE_AND_FORGET,
            completion_event="agent.restart_dispatched",
        )
        self.session_id = session_id
        self.agent_name = agent_name
        self.self_restart = self_restart

    def to_payload(self) -> dict[str, object]:
        args: list[str] = []
        if self.agent_name:
            args.append(self.agent_name)
        return {"session_id": self.session_id, "args": args}


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
            response_mode=ResponseMode.FIRE_AND_FORGET,
            completion_event="session.close_completed",
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
        completion_event: str | None = None,
    ):
        super().__init__(
            command_type=CommandType.SYSTEM,
            request_id=request_id,
            response_mode=response_mode,
            completion_event=completion_event,
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


COMMAND_CLASS_BY_TYPE: dict[CommandType, type[InternalCommand]] = {
    CommandType.CREATE_SESSION: CreateSessionCommand,
    CommandType.HANDLE_VOICE: HandleVoiceCommand,
    CommandType.HANDLE_FILE: HandleFileCommand,
    CommandType.KEYS: KeysCommand,
    CommandType.START_AGENT: StartAgentCommand,
    CommandType.RESUME_AGENT: ResumeAgentCommand,
    CommandType.PROCESS_MESSAGE: ProcessMessageCommand,
    CommandType.RUN_AGENT_COMMAND: RunAgentCommand,
    CommandType.RESTART_AGENT: RestartAgentCommand,
    CommandType.UNSUBSCRIBE_SESSION: UnsubscribeSessionCommand,
    CommandType.GET_SESSION_DATA: GetSessionDataCommand,
    CommandType.CLOSE_SESSION: CloseSessionCommand,
    CommandType.SYSTEM: SystemCommand,
}


def command_from_dict(data: JsonDict) -> InternalCommand:
    """Rebuild an internal command from its cross-computer wire payload."""
    raw_command_type = data.get("command_type")
    if not isinstance(raw_command_type, str):
        raise ValueError("command_type is required")
    command_type = CommandType(raw_command_type)
    command_cls = COMMAND_CLASS_BY_TYPE[command_type]

    constructor_params = signature(command_cls).parameters
    kwargs: dict[str, object] = {}
    for name in constructor_params:
        if name in {"command_type", "computer"} or name not in data:
            continue
        raw_value: object = data[name]
        value: object = raw_value
        if name == "response_mode" and isinstance(raw_value, str):
            value = ResponseMode(raw_value)
        elif name == "launch_intent" and isinstance(raw_value, dict):
            value = SessionLaunchIntent.from_dict(raw_value)
        elif name == "entry_point" and isinstance(raw_value, str):
            value = SessionEntryPoint(raw_value)
        elif name in {"origin_metadata", "data"} and isinstance(raw_value, dict):
            value = dict(raw_value)
        kwargs[name] = value

    command = cast(InternalCommand, cast(Any, command_cls)(**kwargs))
    command.computer = cast(str | None, data.get("computer"))
    raw_response_mode = data.get("response_mode")
    if isinstance(raw_response_mode, str):
        command.response_mode = ResponseMode(raw_response_mode)
    command.completion_event = cast(str | None, data.get("completion_event"))
    return command
