"""Session snapshot, args, and info models for TeleClaude."""

from dataclasses import asdict, dataclass, field
from typing import cast

from teleclaude.api_models import TodoDTO
from teleclaude.core.feedback import get_last_output_summary
from teleclaude.core.session_status import compute_agent_status
from teleclaude.core.shell_identity import optional_shell_safe_identifier
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.session_fields import SessionSnapshotIdentityFields, SessionSnapshotTimestampFields
from teleclaude.types import SystemStats

# re-export for spec test access (tests import MessageMetadata from _snapshot)
from ._session import MessageMetadata as MessageMetadata
from ._session import Session
from ._types import JsonDict


@dataclass
class StartSessionArgs:
    """Typed arguments for starting a session."""

    computer: str
    project_path: str
    title: str
    message: str
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    caller_session_id: str | None = None
    direct: bool = False


@dataclass
class RunAgentCommandArgs:
    """Typed arguments for run-agent command execution."""

    computer: str
    command: str
    args: str = ""
    project: str | None = None
    agent: str = "claude"
    thinking_mode: ThinkingMode = ThinkingMode.SLOW
    subfolder: str = ""
    caller_session_id: str | None = None


@dataclass
class RedisInboundMessage:
    """Typed Redis message parsed from raw stream entry."""

    msg_type: str
    session_id: str | None
    command: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    platform_message_id: str | None = None
    initiator: str | None = None
    project_path: str | None = None
    title: str | None = None
    origin: str | None = None
    launch_intent: dict[str, object] | None = None  # guard: loose-dict
    reply_stream: str | None = None


@dataclass
class SessionSnapshot(
    SessionSnapshotTimestampFields,
    SessionSnapshotIdentityFields,
):
    """Typed session snapshot for list_sessions output."""

    session_id: str
    last_input_origin: str | None
    title: str
    thinking_mode: str | None
    active_agent: str | None
    status: str
    project_path: str | None = None
    subdir: str | None = None
    visibility: str | None = "private"
    system_role: str | None = None
    job: str | None = None
    agent_status: str | None = None

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - Serialization output
        """Convert snapshot to a JSON-compatible dictionary."""
        return {
            "session_id": self.session_id,
            "last_input_origin": self.last_input_origin,
            "title": self.title,
            "project_path": self.project_path,
            "subdir": self.subdir,
            "thinking_mode": self.thinking_mode,
            "active_agent": self.active_agent,
            "status": self.status,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "closed_at": self.closed_at,
            "last_input": self.last_input,
            "last_input_at": self.last_input_at,
            "last_agent_stop_at": self.last_agent_stop_at,
            "last_output_summary": self.last_output_summary,
            "last_output_summary_at": self.last_output_summary_at,
            "last_output_digest": self.last_output_digest,
            "native_session_id": self.native_session_id,
            "tmux_session_name": self.tmux_session_name,
            "initiator_session_id": self.initiator_session_id,
            "detached": self.detached,
            "computer": self.computer,
            "human_email": self.human_email,
            "human_role": self.human_role,
            "visibility": self.visibility,
            "system_role": self.system_role,
            "job": self.job,
            "agent_status": self.agent_status,
        }

    @classmethod
    def from_db_session(cls, session: "Session", computer: str | None = None) -> "SessionSnapshot":
        """Create from database Session object."""
        agent_status = compute_agent_status(
            last_activity=session.last_activity,
            last_input_at=session.last_message_sent_at,
            last_agent_stop_at=session.last_agent_stop_at,
        )
        return cls(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            thinking_mode=session.thinking_mode,
            active_agent=session.active_agent,
            status=session.lifecycle_status,
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            last_input=session.last_message_sent,
            last_input_at=session.last_message_sent_at.isoformat() if session.last_message_sent_at else None,
            last_agent_stop_at=session.last_agent_stop_at.isoformat() if session.last_agent_stop_at else None,
            last_output_summary=get_last_output_summary(session),
            last_output_summary_at=(session.last_output_at.isoformat() if session.last_output_at else None),
            last_output_digest=session.last_output_digest,
            native_session_id=session.native_session_id,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
            detached=session.detached,
            computer=computer,
            human_email=session.human_email,
            human_role=session.human_role,
            visibility=getattr(session, "visibility", None) or "private",
            system_role=session.system_role,
            job=session.job,
            agent_status=agent_status,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionSnapshot":  # guard: loose-dict
        """Create from dict."""
        return cls(
            session_id=str(data["session_id"]),
            last_input_origin=str(data.get("last_input_origin")) if data.get("last_input_origin") else None,
            title=str(data["title"]),
            project_path=str(data.get("project_path")) if data.get("project_path") else None,
            subdir=str(data.get("subdir")) if data.get("subdir") else None,
            thinking_mode=str(data["thinking_mode"]) if data.get("thinking_mode") is not None else None,
            active_agent=str(data.get("active_agent")) if data.get("active_agent") else None,
            status=str(data["status"]),
            created_at=str(data.get("created_at")) if data.get("created_at") else None,
            last_activity=str(data.get("last_activity")) if data.get("last_activity") else None,
            last_input=str(data.get("last_input")) if data.get("last_input") else None,
            last_input_at=str(data.get("last_input_at")) if data.get("last_input_at") else None,
            last_agent_stop_at=str(data.get("last_agent_stop_at")) if data.get("last_agent_stop_at") else None,
            last_output_summary=(
                str(data.get("last_output_summary") or data.get("last_output"))
                if (data.get("last_output_summary") or data.get("last_output"))
                else None
            ),
            last_output_summary_at=(
                str(data.get("last_output_summary_at") or data.get("last_output_at"))
                if (data.get("last_output_summary_at") or data.get("last_output_at"))
                else None
            ),
            last_output_digest=str(data.get("last_output_digest")) if data.get("last_output_digest") else None,
            native_session_id=str(data.get("native_session_id")) if data.get("native_session_id") else None,
            tmux_session_name=optional_shell_safe_identifier(
                data.get("tmux_session_name"), "session tmux_session_name"
            ),
            initiator_session_id=str(data.get("initiator_session_id")) if data.get("initiator_session_id") else None,
            detached=bool(data.get("detached")) if data.get("detached") is not None else False,
            computer=str(data.get("computer")) if data.get("computer") else None,
            human_email=str(data.get("human_email")) if data.get("human_email") else None,
            human_role=str(data.get("human_role")) if data.get("human_role") else None,
            visibility=str(data.get("visibility")) if data.get("visibility") else "private",
            system_role=str(data.get("system_role")) if data.get("system_role") else None,
            job=str(data.get("job")) if data.get("job") else None,
            agent_status=str(data.get("agent_status")) if data.get("agent_status") else None,
        )


@dataclass
class AgentStartArgs:
    """Typed arguments for agent start."""

    agent_name: str
    thinking_mode: ThinkingMode
    user_args: list[str]


@dataclass
class AgentResumeArgs:
    """Typed arguments for agent resume."""

    agent_name: str
    native_session_id: str | None
    thinking_mode: ThinkingMode | None


@dataclass
class KillArgs:
    """Typed arguments for kill command."""


@dataclass
class SystemCommandArgs:
    """Typed arguments for system commands."""

    command: str


@dataclass
class MessagePayload:
    """Payload for MESSAGE events."""

    session_id: str
    text: str
    project_path: str | None = None
    title: str | None = None


@dataclass
class ComputerInfo:
    """Information about a computer (local or remote)."""

    name: str
    status: str
    user: str | None = None
    host: str | None = None
    role: str | None = None
    is_local: bool = False
    system_stats: SystemStats | None = None
    tmux_binary: str | None = None

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict
        """Convert computer info to a JSON-compatible dictionary."""
        return cast(dict[str, object], asdict(self))  # guard: loose-dict - serialization output


@dataclass
class ProjectInfo:
    """Information about a project directory."""

    name: str
    path: str
    description: str | None = None
    computer: str | None = None
    todos: list[TodoDTO] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ProjectInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        raw_todos = data.get("todos") or []
        todo_list = list(raw_todos) if isinstance(raw_todos, list) else []
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            description=str(data.get("description") or data.get("desc") or ""),
            computer=cast(str | None, data.get("computer")),
            todos=[
                TodoDTO.model_validate(t) for t in todo_list if isinstance(t, dict)
            ],  # guard: loose-dict - JSON deserialization
        )

    def to_dict(self) -> JsonDict:  # guard: loose-dict
        """Convert to dict."""
        result = cast(JsonDict, asdict(self))
        result["todos"] = [t.model_dump() for t in self.todos]
        return result


@dataclass
class CommandPayload:
    """Generic command payload with args."""

    session_id: str
    args: list[str]
    project_path: str | None = None
    title: str | None = None
