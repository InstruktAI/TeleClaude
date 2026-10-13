"""Session snapshot, args, and info models for TeleClaude."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.core.agent_status_projection import (
    project_peer_agent_status,
    project_readiness_fields,
    read_session_agent_status,
)
from teleclaude.core.feedback import get_last_output_summary
from teleclaude.core.roles import legacy_system_role
from teleclaude.core.session_status import AgentStatusReason, AgentStatusValue
from teleclaude.core.shell_identity import optional_shell_safe_identifier
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.session_fields import (
    SESSION_PRINCIPAL_FIELD,
    SessionSnapshotIdentityFields,
    SessionSnapshotTimestampFields,
)
from teleclaude.types import SystemStats

# re-export for spec test access (tests import MessageMetadata from _snapshot)
from ._session import MessageMetadata as MessageMetadata
from ._session import Session
from ._types import JsonDict, json_int, to_json_dict

_INITIALIZING_FOR_SECONDS_FIELD = "initializing_for_seconds"

_AGENT_STATUS_FIELD = "agent_status"
_AGENT_STATUS_EXACT_FIELD = "agent_status_exact"
_AGENT_STATUS_REASON_FIELD = "agent_status_reason"
_AGENT_STATUS_SINCE_FIELD = "agent_status_since"
_CONFIG_SUBJECT_FIELD = "config_subject"
_SUBJECT_OWNER_FIELD = "subject_owner"
_PROJECT_SUBJECT_FIELD = "subject"
_PROJECT_OWNER_FIELD = "owner"
logger = get_logger(__name__)


def _parse_peer_agent_status(data: Mapping[str, object]) -> tuple[AgentStatusValue, AgentStatusReason | None]:
    """Read exact peer status when present; otherwise use the legacy field."""
    status_key = _AGENT_STATUS_EXACT_FIELD if _AGENT_STATUS_EXACT_FIELD in data else _AGENT_STATUS_FIELD
    status_raw = data.get(status_key, AgentStatusValue.UNKNOWN)
    status = AgentStatusValue(str(status_raw))
    reason_raw = data.get(_AGENT_STATUS_REASON_FIELD)
    reason = AgentStatusReason(str(reason_raw)) if reason_raw else None
    return status, reason


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
    caller_principal: str
    command_payload: JsonDict | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    platform_message_id: str | None = None
    initiator: str | None = None
    project_path: str | None = None
    title: str | None = None
    origin: str | None = None
    origin_metadata: JsonDict | None = None
    launch_intent: JsonDict | None = None
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
    origin_metadata: JsonDict = field(default_factory=dict)
    project_path: str | None = None
    subdir: str | None = None
    config_subject: str | None = None
    subject_owner: str | None = None
    command: str | None = None
    working_slug: str | None = None
    visibility: str | None = "private"
    role: str | None = None
    # Older-reader projection of ``role``, kept populated for nodes that predate the role catalog; read for display only.
    system_role: str | None = None
    job: str | None = None
    agent_status: str | None = None
    agent_status_reason: str | None = None
    agent_status_since: str | None = None
    next_reminder_slug: str | None = None
    next_reminder_at: str | None = None
    conversation_url: str | None = None
    runtime_start_observed: bool = False
    runtime_activity_at: str | None = None
    lifecycle_transitioned_at: str | None = None
    lifecycle_transition_reason: str | None = None
    initializing_for_seconds: int | None = None
    attention: str | None = None
    procedure: str | None = None
    last_output_stop_at: str | None = None

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - Serialization output
        """Convert snapshot to a JSON-compatible dictionary."""
        return {
            "session_id": self.session_id,
            "last_input_origin": self.last_input_origin,
            "title": self.title,
            "project_path": self.project_path,
            "subdir": self.subdir,
            _CONFIG_SUBJECT_FIELD: self.config_subject,
            _SUBJECT_OWNER_FIELD: self.subject_owner,
            "command": self.command,
            "working_slug": self.working_slug,
            "thinking_mode": self.thinking_mode,
            "active_agent": self.active_agent,
            "status": self.status,
            "origin_metadata": self.origin_metadata,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "closed_at": self.closed_at,
            "last_input": self.last_input,
            "last_input_at": self.last_input_at,
            "last_agent_stop_at": self.last_agent_stop_at,
            "last_agent_idle_at": self.last_agent_idle_at,
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
            SESSION_PRINCIPAL_FIELD: self.principal,
            "visibility": self.visibility,
            "role": self.role,
            "system_role": self.system_role,
            "job": self.job,
            _AGENT_STATUS_FIELD: self.agent_status,
            _AGENT_STATUS_REASON_FIELD: self.agent_status_reason,
            _AGENT_STATUS_SINCE_FIELD: self.agent_status_since,
            "next_reminder_slug": self.next_reminder_slug,
            "next_reminder_at": self.next_reminder_at,
            "conversation_url": self.conversation_url,
            "runtime_start_observed": self.runtime_start_observed,
            "runtime_activity_at": self.runtime_activity_at,
            "lifecycle_transitioned_at": self.lifecycle_transitioned_at,
            "lifecycle_transition_reason": self.lifecycle_transition_reason,
            "initializing_for_seconds": self.initializing_for_seconds,
            "attention": self.attention,
            "procedure": self.procedure,
            "last_output_stop_at": self.last_output_stop_at,
        }

    def to_peer_dict(self) -> dict[str, object]:  # guard: loose-dict - Serialization output
        """Serialize the compatible peer status plus this node's exact status."""
        data = self.to_dict()
        exact_status = AgentStatusValue(self.agent_status or AgentStatusValue.UNKNOWN)
        data[_AGENT_STATUS_FIELD] = project_peer_agent_status(exact_status).value
        data[_AGENT_STATUS_EXACT_FIELD] = exact_status.value
        return data

    @classmethod
    def from_db_session(cls, session: "Session", computer: str | None = None) -> "SessionSnapshot":
        """Create from database Session object."""
        now = datetime.now(UTC)
        initializing_for_seconds, attention, procedure = project_readiness_fields(session, now)
        from teleclaude.core.db import (  # noqa: PLC0415 - core.db imports core.models, so resolve only after model initialization
            SessionIdentityError,
            resolve_session_principal,
        )

        try:
            principal, _role = resolve_session_principal(session)
        except SessionIdentityError:
            principal = None
        return cls(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            config_subject=session.config_subject,
            subject_owner=session.subject_owner,
            thinking_mode=session.thinking_mode,
            active_agent=session.active_agent,
            status=session.lifecycle_status,
            command=session.command,
            working_slug=session.working_slug,
            origin_metadata=dict(session.origin_metadata),
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            closed_at=session.closed_at.isoformat() if session.closed_at else None,
            last_input=session.last_input,
            last_input_at=(
                session.last_input_written_at.isoformat()
                if session.last_input_written_at
                else (session.last_message_sent_at.isoformat() if session.last_message_sent_at else None)
            ),
            last_agent_stop_at=session.last_agent_stop_at.isoformat() if session.last_agent_stop_at else None,
            last_agent_idle_at=session.last_agent_idle_at.isoformat() if session.last_agent_idle_at else None,
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
            principal=principal,
            visibility=getattr(session, "visibility", None) or "private",
            role=session.role,
            system_role=legacy_system_role(session.role),
            job=session.job,
            agent_status=read_session_agent_status(session).value,
            agent_status_reason=session.agent_status_reason.value if session.agent_status_reason else None,
            agent_status_since=session.agent_status_since.isoformat() if session.agent_status_since else None,
            next_reminder_slug=None,
            next_reminder_at=None,
            conversation_url=None,
            runtime_start_observed=session.runtime_start_observed,
            runtime_activity_at=session.runtime_activity_at.isoformat() if session.runtime_activity_at else None,
            lifecycle_transitioned_at=(
                session.lifecycle_transitioned_at.isoformat() if session.lifecycle_transitioned_at else None
            ),
            lifecycle_transition_reason=session.lifecycle_transition_reason,
            initializing_for_seconds=initializing_for_seconds,
            attention=attention,
            procedure=procedure,
            last_output_stop_at=(session.last_output_stop_at.isoformat() if session.last_output_stop_at else None),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SessionSnapshot":  # guard: loose-dict
        """Create from dict."""
        agent_status, agent_status_reason = _parse_peer_agent_status(data)
        return cls(
            session_id=str(data["session_id"]),
            last_input_origin=str(data.get("last_input_origin")) if data.get("last_input_origin") else None,
            title=str(data["title"]),
            project_path=str(data.get("project_path")) if data.get("project_path") else None,
            subdir=str(data.get("subdir")) if data.get("subdir") else None,
            config_subject=(
                str(data.get(_CONFIG_SUBJECT_FIELD)) if data.get(_CONFIG_SUBJECT_FIELD) is not None else None
            ),
            subject_owner=(str(data.get(_SUBJECT_OWNER_FIELD)) if data.get(_SUBJECT_OWNER_FIELD) is not None else None),
            command=str(data.get("command")) if data.get("command") else None,
            working_slug=str(data.get("working_slug")) if data.get("working_slug") else None,
            thinking_mode=str(data["thinking_mode"]) if data.get("thinking_mode") is not None else None,
            active_agent=str(data.get("active_agent")) if data.get("active_agent") else None,
            status=str(data["status"]),
            origin_metadata=(to_json_dict(_om) if isinstance((_om := data.get("origin_metadata")), dict) else {}),
            created_at=str(data.get("created_at")) if data.get("created_at") else None,
            last_activity=str(data.get("last_activity")) if data.get("last_activity") else None,
            last_input=str(data.get("last_input")) if data.get("last_input") else None,
            last_input_at=str(data.get("last_input_at")) if data.get("last_input_at") else None,
            last_agent_stop_at=str(data.get("last_agent_stop_at")) if data.get("last_agent_stop_at") else None,
            last_agent_idle_at=str(data.get("last_agent_idle_at")) if data.get("last_agent_idle_at") else None,
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
            principal=(str(data.get(SESSION_PRINCIPAL_FIELD)) if data.get(SESSION_PRINCIPAL_FIELD) else None),
            visibility=str(data.get("visibility")) if data.get("visibility") else "private",
            role=str(data.get("role")) if data.get("role") else None,
            system_role=str(data.get("system_role")) if data.get("system_role") else None,
            job=str(data.get("job")) if data.get("job") else None,
            agent_status=agent_status.value,
            agent_status_reason=agent_status_reason.value if agent_status_reason else None,
            agent_status_since=(
                str(data.get(_AGENT_STATUS_SINCE_FIELD)) if data.get(_AGENT_STATUS_SINCE_FIELD) else None
            ),
            next_reminder_slug=(str(data.get("next_reminder_slug")) if data.get("next_reminder_slug") else None),
            next_reminder_at=str(data.get("next_reminder_at")) if data.get("next_reminder_at") else None,
            conversation_url=str(data.get("conversation_url")) if data.get("conversation_url") else None,
            runtime_start_observed=bool(data.get("runtime_start_observed", False)),
            runtime_activity_at=str(data.get("runtime_activity_at")) if data.get("runtime_activity_at") else None,
            lifecycle_transitioned_at=(
                str(data.get("lifecycle_transitioned_at")) if data.get("lifecycle_transitioned_at") else None
            ),
            lifecycle_transition_reason=(
                str(data.get("lifecycle_transition_reason")) if data.get("lifecycle_transition_reason") else None
            ),
            initializing_for_seconds=(
                json_int(data[_INITIALIZING_FOR_SECONDS_FIELD])
                if data.get(_INITIALIZING_FOR_SECONDS_FIELD) is not None
                else None
            ),
            attention=str(data.get("attention")) if data.get("attention") else None,
            procedure=str(data.get("procedure")) if data.get("procedure") else None,
            last_output_stop_at=(str(data.get("last_output_stop_at")) if data.get("last_output_stop_at") else None),
        )


def parse_peer_session_snapshots(data: list[JsonDict], computer: str) -> list[SessionSnapshot]:
    """Decode tolerant peer snapshots and discard malformed status claims."""
    snapshots: list[SessionSnapshot] = []
    for session_data in data:
        try:
            snapshots.append(SessionSnapshot.from_dict(session_data))
        except ValueError as exc:
            logger.warning(
                "Discarding malformed session snapshot",
                computer=computer,
                error=str(exc),
            )
    return snapshots


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
    version: str | None = None
    channel: str | None = None
    capability_set: list[str] = field(default_factory=list)
    is_master: bool | None = None
    # Conversation adapters this computer runs; ``None`` when unknown.
    conversation_adapters: list[str] | None = None

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
    subject: str | None = None
    owner: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProjectInfo":  # guard: loose-dict
        """Create from dict with field mapping."""
        raw_todos = data.get("todos") or []
        todo_list = list(raw_todos) if isinstance(raw_todos, list) else []
        raw_subject = data.get(_PROJECT_SUBJECT_FIELD)
        raw_owner = data.get(_PROJECT_OWNER_FIELD)
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            description=str(data.get("description") or data.get("desc") or ""),
            computer=cast(str | None, data.get("computer")),
            subject=raw_subject if isinstance(raw_subject, str) else None,
            owner=raw_owner if isinstance(raw_owner, str) else None,
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
