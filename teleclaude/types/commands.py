"""Internal command models for TeleClaude."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from teleclaude.core.models import SessionLaunchIntent


class CommandType(str, Enum):
    """Internal command types."""

    CREATE_SESSION = "create_session"
    START_AGENT = "start_agent"
    RESUME_AGENT = "resume_agent"
    SEND_MESSAGE = "send_message"
    SEND_AGENT_COMMAND = "send_agent_command"
    CLOSE_SESSION = "close_session"
    SYSTEM = "system"


@dataclass(kw_only=True)
class InternalCommand:
    """Base class for all internal commands."""

    command_type: CommandType
    request_id: Optional[str] = None


@dataclass(kw_only=True)
class CreateSessionCommand(InternalCommand):
    """Intent to create a new session."""

    project_path: str
    title: Optional[str] = None
    subdir: Optional[str] = None
    working_slug: Optional[str] = None
    initiator_session_id: Optional[str] = None
    adapter_type: str = "unknown"
    channel_metadata: Optional[Dict[str, object]] = None
    launch_intent: Optional["SessionLaunchIntent"] = None

    def __init__(
        self,
        *,
        project_path: str,
        title: Optional[str] = None,
        subdir: Optional[str] = None,
        working_slug: Optional[str] = None,
        initiator_session_id: Optional[str] = None,
        adapter_type: str = "unknown",
        channel_metadata: Optional[Dict[str, object]] = None,
        launch_intent: Optional["SessionLaunchIntent"] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.CREATE_SESSION, request_id=request_id)
        self.project_path = project_path
        self.title = title
        self.subdir = subdir
        self.working_slug = working_slug
        self.initiator_session_id = initiator_session_id
        self.adapter_type = adapter_type
        self.channel_metadata = channel_metadata
        self.launch_intent = launch_intent


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


@dataclass(kw_only=True)
class SendAgentCommand(InternalCommand):
    """Intent to send a slash command to an agent."""

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
        super().__init__(command_type=CommandType.SEND_AGENT_COMMAND, request_id=request_id)
        self.session_id = session_id
        self.command = command
        self.args = args


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


@dataclass(kw_only=True)
class SystemCommand(InternalCommand):
    """Intent to perform a system-level operation (list sessions, list projects, etc.)."""

    command: str
    args: List[str] = field(default_factory=list)

    def __init__(
        self,
        *,
        command: str,
        args: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(command_type=CommandType.SYSTEM, request_id=request_id)
        self.command = command
        self.args = args or []
