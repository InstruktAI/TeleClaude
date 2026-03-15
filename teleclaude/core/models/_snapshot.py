"""Session snapshot, args, and info models for TeleClaude."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import cast

from teleclaude.core.feedback import get_last_output_summary
from teleclaude.types import SystemStats

from ._session import Session, SessionMetadata
from ._types import JsonDict


class ThinkingMode(str, Enum):
    """Model tier: fast/med/slow."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"
    DEEP = "deep"


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
    channel_metadata: dict[str, object] | None = None  # guard: loose-dict
    initiator: str | None = None
    project_path: str | None = None
    title: str | None = None
    origin: str | None = None
    launch_intent: dict[str, object] | None = None  # guard: loose-dict
    reply_stream: str | None = None


@dataclass
class SessionSnapshot:
    """Typed session snapshot for list_sessions output."""

    session_id: str
    last_input_origin: str | None
    title: str
    thinking_mode: str | None
    active_agent: str | None
    status: str
    project_path: str | None = None
    subdir: str | None = None
    created_at: str | None = None
    last_activity: str | None = None
    closed_at: str | None = None
    last_input: str | None = None
    last_input_at: str | None = None
    last_output_summary: str | None = None
    last_output_summary_at: str | None = None
    last_output_digest: str | None = None
    native_session_id: str | None = None
    tmux_session_name: str | None = None
    initiator_session_id: str | None = None
    computer: str | None = None
    human_email: str | None = None
    human_role: str | None = None
    visibility: str | None = "private"
    session_metadata: SessionMetadata | None = None

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - Serialization output
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
            "last_output_summary": self.last_output_summary,
            "last_output_summary_at": self.last_output_summary_at,
            "last_output_digest": self.last_output_digest,
            "native_session_id": self.native_session_id,
            "tmux_session_name": self.tmux_session_name,
            "initiator_session_id": self.initiator_session_id,
            "computer": self.computer,
            "human_email": self.human_email,
            "human_role": self.human_role,
            "visibility": self.visibility,
            "session_metadata": asdict(self.session_metadata) if self.session_metadata else None,
        }

    @classmethod
    def from_db_session(cls, session: "Session", computer: str | None = None) -> "SessionSnapshot":
        """Create from database Session object."""
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
            last_output_summary=get_last_output_summary(session),
            last_output_summary_at=(session.last_output_at.isoformat() if session.last_output_at else None),
            last_output_digest=session.last_output_digest,
            native_session_id=session.native_session_id,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
            computer=computer,
            human_email=session.human_email,
            human_role=session.human_role,
            visibility=getattr(session, "visibility", None) or "private",
            session_metadata=session.session_metadata,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionSnapshot":  # guard: loose-dict
        """Create from dict."""
        sm_raw = data.get("session_metadata")
        sm: SessionMetadata | None = None
        if isinstance(sm_raw, dict):
            sm = SessionMetadata(
                **{
                    k: v
                    for k, v in sm_raw.items()
                    if k in {"system_role", "job", "human_email", "human_role", "principal"}
                }
            )
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
            tmux_session_name=str(data.get("tmux_session_name")) if data.get("tmux_session_name") else None,
            initiator_session_id=str(data.get("initiator_session_id")) if data.get("initiator_session_id") else None,
            computer=str(data.get("computer")) if data.get("computer") else None,
            human_email=str(data.get("human_email")) if data.get("human_email") else None,
            human_role=str(data.get("human_role")) if data.get("human_role") else None,
            visibility=str(data.get("visibility")) if data.get("visibility") else "private",
            session_metadata=sm,
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

    pass


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
        return cast(dict[str, object], asdict(self))


@dataclass
class TodoInfo:
    """Information about a work item todo."""

    slug: str
    status: str
    description: str | None = None
    has_requirements: bool = False
    has_impl_plan: bool = False
    build_status: str | None = None
    review_status: str | None = None
    dor_score: int | None = None
    deferrals_status: str | None = None
    findings_count: int = 0
    files: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    group: str | None = None
    delivered_at: str | None = None
    prepare_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TodoInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        dor_score_raw = data.get("dor_score")
        dor_score: int | None
        try:
            dor_score = int(dor_score_raw) if dor_score_raw is not None else None
        except (TypeError, ValueError):
            dor_score = None

        return cls(
            slug=str(data.get("slug", "")),
            status=str(data.get("status", "pending")),
            description=str(data.get("description") or data.get("title") or ""),
            has_requirements=bool(data.get("has_requirements", False)),
            has_impl_plan=bool(data.get("has_impl_plan", False)),
            build_status=cast(str | None, data.get("build_status")),
            review_status=cast(str | None, data.get("review_status")),
            dor_score=dor_score,
            deferrals_status=cast(str | None, data.get("deferrals_status")),
            findings_count=int(data.get("findings_count", 0) or 0),
            files=[str(f) for f in cast(list[object], data.get("files", []))],
            after=[str(a) for a in cast(list[object], data.get("after", []))],
            group=cast(str | None, data.get("group")),
            delivered_at=cast(str | None, data.get("delivered_at")),
            prepare_phase=cast(str | None, data.get("prepare_phase")),
            integration_phase=cast(str | None, data.get("integration_phase")),
            finalize_status=cast(str | None, data.get("finalize_status")),
        )

    def to_dict(self) -> JsonDict:  # guard: loose-dict
        """Convert to dict."""
        return cast(JsonDict, asdict(self))


@dataclass
class ProjectInfo:
    """Information about a project directory."""

    name: str
    path: str
    description: str | None = None
    computer: str | None = None
    todos: list[TodoInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ProjectInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        # fmt: off
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            description=str(data.get("description") or data.get("desc") or ""),
            computer=cast(str | None, data.get("computer")),
            todos=[TodoInfo.from_dict(t) for t in cast(list[dict[str, object]], data.get("todos", []))],  # guard: loose-dict
        )
        # fmt: on

    def to_dict(self) -> JsonDict:  # guard: loose-dict
        """Convert to dict."""
        result = cast(JsonDict, asdict(self))
        result["todos"] = [t.to_dict() for t in self.todos]
        return result


@dataclass
class CommandPayload:
    """Generic command payload with args."""

    session_id: str
    args: list[str]
    project_path: str | None = None
    title: str | None = None
