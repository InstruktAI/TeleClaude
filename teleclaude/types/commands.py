"""Internal command models for TeleClaude."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from teleclaude.core.models import SessionLaunchIntent


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
    GET_SESSION_DATA = "get_session_data"
    CLOSE_SESSION = "close_session"
    SYSTEM = "system_command"


@dataclass(kw_only=True)
class InternalCommand:
    """Base class for all internal commands."""

    command_type: CommandType
    request_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        """Return payload dict for adapter event dispatch."""
        return {}


@dataclass(kw_only=True)
class CreateSessionCommand(InternalCommand):
    """Intent to create a new session."""

    project_path: str
    origin: str
    title: str | None = None
    subdir: str | None = None
    working_slug: str | None = None
    initiator_session_id: str | None = None
    skip_listener_registration: bool = False
    channel_metadata: dict[str, object] | None = None
    launch_intent: Optional["SessionLaunchIntent"] = None
    auto_command: str | None = None
    session_metadata: dict[str, object] | None = None  # Generic metadata injection

    def __init__(
        self,
        *,
        project_path: str,
        origin: str,
        title: str | None = None,
        subdir: str | None = None,
        working_slug: str | None = None,
        initiator_session_id: str | None = None,
        skip_listener_registration: bool = False,
        channel_metadata: dict[str, object] | None = None,
        launch_intent: Optional["SessionLaunchIntent"] = None,
        auto_command: str | None = None,
        session_metadata: dict[str, object] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.CREATE_SESSION, request_id=request_id)
        self.project_path = project_path
        self.origin = origin
        self.title = title
        self.subdir = subdir
        self.working_slug = working_slug
        self.initiator_session_id = initiator_session_id
        self.skip_listener_registration = skip_listener_registration
        self.channel_metadata = channel_metadata
        self.launch_intent = launch_intent
        self.auto_command = auto_command
        self.session_metadata = session_metadata

    def to_payload(self) -> dict[str, object]:
        args: list[str] = [self.title] if self.title else []
        return {"session_id": "", "args": args}


@dataclass(kw_only=True)
class StartAgentCommand(InternalCommand):
    """Intent to start an agent in an existing session."""

    session_id: str
    agent_name: str
    thinking_mode: str = "slow"
    args: list[str] = field(default_factory=list)

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        thinking_mode: str = "slow",
        args: list[str] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.START_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.thinking_mode = thinking_mode
        self.args = args or []

    def to_payload(self) -> dict[str, object]:
        args = [self.agent_name] + list(self.args)
        return {"session_id": self.session_id, "args": args}


@dataclass(kw_only=True)
class ResumeAgentCommand(InternalCommand):
    """Intent to resume an agent in an existing session."""

    session_id: str
    agent_name: str | None = None
    native_session_id: str | None = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str | None = None,
        native_session_id: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.RESUME_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.native_session_id = native_session_id

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

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"session_id": self.session_id, "text": self.text, "origin": self.origin}
        if self.actor_id is not None:
            payload["actor_id"] = self.actor_id
        if self.actor_name is not None:
            payload["actor_name"] = self.actor_name
        if self.actor_avatar_url is not None:
            payload["actor_avatar_url"] = self.actor_avatar_url
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

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.RESTART_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name

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
class CloseSessionCommand(InternalCommand):
    """Intent to close a session."""

    session_id: str

    def __init__(
        self,
        *,
        session_id: str,
        request_id: str | None = None,
    ):
        super().__init__(command_type=CommandType.CLOSE_SESSION, request_id=request_id)
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
    ):
        super().__init__(command_type=CommandType.SYSTEM, request_id=request_id)
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
