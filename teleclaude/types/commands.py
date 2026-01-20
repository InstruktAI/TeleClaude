"""Internal command models for TeleClaude."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional

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
    SEND_MESSAGE = "send_message"
    RUN_AGENT_COMMAND = "run_agent_command"
    RESTART_AGENT = "restart_agent"
    GET_SESSION_DATA = "get_session_data"
    CLOSE_SESSION = "close_session"
    SYSTEM = "system_command"


@dataclass(kw_only=True)
class InternalCommand:
    """Base class for all internal commands."""

    command_type: CommandType
    request_id: Optional[str] = None

    def to_payload(self) -> Dict[str, object]:
        """Return payload dict for adapter event dispatch."""
        return {}


@dataclass(kw_only=True)
class CreateSessionCommand(InternalCommand):
    """Intent to create a new session."""

    project_path: str
    title: Optional[str] = None
    subdir: Optional[str] = None
    working_slug: Optional[str] = None
    initiator_session_id: Optional[str] = None
    origin: str = "unknown"
    channel_metadata: Optional[Dict[str, object]] = None
    launch_intent: Optional["SessionLaunchIntent"] = None
    auto_command: Optional[str] = None

    def __init__(
        self,
        *,
        project_path: str,
        title: Optional[str] = None,
        subdir: Optional[str] = None,
        working_slug: Optional[str] = None,
        initiator_session_id: Optional[str] = None,
        origin: str = "unknown",
        channel_metadata: Optional[Dict[str, object]] = None,
        launch_intent: Optional["SessionLaunchIntent"] = None,
        auto_command: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.CREATE_SESSION, request_id=request_id)
        self.project_path = project_path
        self.title = title
        self.subdir = subdir
        self.working_slug = working_slug
        self.initiator_session_id = initiator_session_id
        self.origin = origin
        self.channel_metadata = channel_metadata
        self.launch_intent = launch_intent
        self.auto_command = auto_command

    def to_payload(self) -> Dict[str, object]:
        args: List[str] = [self.title] if self.title else []
        return {"session_id": "", "args": args}


@dataclass(kw_only=True)
class StartAgentCommand(InternalCommand):
    """Intent to start an agent in an existing session."""

    session_id: str
    agent_name: str
    thinking_mode: str = "slow"
    args: List[str] = field(default_factory=list)

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        thinking_mode: str = "slow",
        args: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.START_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.thinking_mode = thinking_mode
        self.args = args or []

    def to_payload(self) -> Dict[str, object]:
        args = [self.agent_name] + list(self.args)
        return {"session_id": self.session_id, "args": args}


@dataclass(kw_only=True)
class ResumeAgentCommand(InternalCommand):
    """Intent to resume an agent in an existing session."""

    session_id: str
    agent_name: Optional[str] = None
    native_session_id: Optional[str] = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: Optional[str] = None,
        native_session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.RESUME_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name
        self.native_session_id = native_session_id

    def to_payload(self) -> Dict[str, object]:
        args: List[str] = []
        if self.agent_name:
            args.append(self.agent_name)
        if self.native_session_id:
            args.append(self.native_session_id)
        return {"session_id": self.session_id, "args": args}


@dataclass(kw_only=True)
class SendMessageCommand(InternalCommand):
    """Intent to send a message to a session."""

    session_id: str
    text: str

    def __init__(
        self,
        *,
        session_id: str,
        text: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.SEND_MESSAGE, request_id=request_id)
        self.session_id = session_id
        self.text = text

    def to_payload(self) -> Dict[str, object]:
        return {"session_id": self.session_id, "text": self.text}


@dataclass(kw_only=True)
class HandleVoiceCommand(InternalCommand):
    """Intent to handle a voice input for a session."""

    session_id: str
    file_path: str
    duration: Optional[float] = None
    message_id: Optional[str] = None
    message_thread_id: Optional[int] = None
    origin: Optional[str] = None

    def __init__(
        self,
        *,
        session_id: str,
        file_path: str,
        duration: Optional[float] = None,
        message_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        origin: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.HANDLE_VOICE, request_id=request_id)
        self.session_id = session_id
        self.file_path = file_path
        self.duration = duration
        self.message_id = message_id
        self.message_thread_id = message_thread_id
        self.origin = origin

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
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
        return payload


@dataclass(kw_only=True)
class HandleFileCommand(InternalCommand):
    """Intent to handle a file upload for a session."""

    session_id: str
    file_path: str
    filename: str
    caption: Optional[str] = None
    file_size: int = 0

    def __init__(
        self,
        *,
        session_id: str,
        file_path: str,
        filename: str,
        caption: Optional[str] = None,
        file_size: int = 0,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.HANDLE_FILE, request_id=request_id)
        self.session_id = session_id
        self.file_path = file_path
        self.filename = filename
        self.caption = caption
        self.file_size = file_size

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
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
    args: List[str] = field(default_factory=list)

    def __init__(
        self,
        *,
        session_id: str,
        key: str,
        args: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.KEYS, request_id=request_id)
        self.session_id = session_id
        self.key = key
        self.args = args or []

    def to_payload(self) -> Dict[str, object]:
        return {"session_id": self.session_id, "args": list(self.args)}


@dataclass(kw_only=True)
class RunAgentCommand(InternalCommand):
    """Intent to run a slash command inside an agent session."""

    session_id: str
    command: str
    args: str = ""

    def __init__(
        self,
        *,
        session_id: str,
        command: str,
        args: str = "",
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.RUN_AGENT_COMMAND, request_id=request_id)
        self.session_id = session_id
        self.command = command
        self.args = args

    def to_payload(self) -> Dict[str, object]:
        return {"session_id": self.session_id, "command": self.command, "args": self.args}


@dataclass(kw_only=True)
class RestartAgentCommand(InternalCommand):
    """Intent to restart an agent in the session."""

    session_id: str
    agent_name: Optional[str] = None

    def __init__(
        self,
        *,
        session_id: str,
        agent_name: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.RESTART_AGENT, request_id=request_id)
        self.session_id = session_id
        self.agent_name = agent_name

    def to_payload(self) -> Dict[str, object]:
        args: List[str] = []
        if self.agent_name:
            args.append(self.agent_name)
        return {"session_id": self.session_id, "args": args}


@dataclass(kw_only=True)
class GetSessionDataCommand(InternalCommand):
    """Intent to fetch session transcript data."""

    session_id: str
    since_timestamp: Optional[str] = None
    until_timestamp: Optional[str] = None
    tail_chars: int = 5000

    def __init__(
        self,
        *,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 5000,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.GET_SESSION_DATA, request_id=request_id)
        self.session_id = session_id
        self.since_timestamp = since_timestamp
        self.until_timestamp = until_timestamp
        self.tail_chars = tail_chars

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {"session_id": self.session_id}
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
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.CLOSE_SESSION, request_id=request_id)
        self.session_id = session_id

    def to_payload(self) -> Dict[str, object]:
        return {"session_id": self.session_id, "args": []}


@dataclass(kw_only=True)
class SystemCommand(InternalCommand):
    """Intent to perform a system-level operation (list sessions, list projects, etc.)."""

    command: str
    args: List[str] = field(default_factory=list)
    data: Optional[Dict[str, object]] = None
    session_id: Optional[str] = None

    def __init__(
        self,
        *,
        command: str,
        args: Optional[List[str]] = None,
        data: Optional[Dict[str, object]] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.SYSTEM, request_id=request_id)
        self.command = command
        self.args = args or []
        self.data = data
        self.session_id = session_id

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {"command": self.command, "args": self.args}
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.data is not None:
            payload["data"] = self.data
            if "from_computer" in self.data:
                payload["from_computer"] = self.data["from_computer"]
        return payload
