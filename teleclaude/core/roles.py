"""Agent role catalog: the one place a role's reach, class and header label are composed.

A capability is one named unit of reach — one family of ``telec`` commands, or one grant to start
sessions of one class. A role declares an explicit capability set; a role marked ``full_reach``
reaches every capability. Every consumer that asks what a role may do or what kind of session it is
reads this catalog and keeps no role list of its own
(``local/projects/teleclaude/spec/feature/identity/agent-roles``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_UNKNOWN_ROLE_LOG = "Session %s records role %r, which the role catalog does not name; every role-gated act is refused"


class Capability(StrEnum):
    """One command family, or one dispatch grant, a role may reach."""

    DOCS_READ = "docs-read"
    TODO_READ = "todo-read"
    TODO_WRITE = "todo-write"
    ARTIFACT_READ = "artifact-read"
    ARTIFACT_WRITE = "artifact-write"
    STAMP = "stamp"
    TODO_ORCHESTRATION = "todo-orchestration"
    INTEGRATION = "integration"
    MAINTENANCE_RECOVERY = "maintenance-recovery"
    MEMORY_CURATION = "memory-curation"
    SESSION_OBSERVE = "session-observe"
    TRANSCRIPT_READ = "transcript-read"
    OPERATION_READ = "operation-read"
    SESSION_ACT = "session-act"
    SELF_ACTS = "self-acts"
    MESSAGING = "messaging"
    AUDIO = "audio"
    JOBS = "jobs"
    JOBS_READ = "jobs-read"
    JOB_REPORT = "job-report"
    CONFIG = "config"
    CONFIG_READ = "config-read"
    REMINDERS = "reminders"
    CODE_CHECK = "code-check"
    CODE = "code"
    MCP = "mcp"
    PEER_TALK = "peer-talk"
    MEMORIES_READ = "memories-read"
    DISPATCH_WORKER = "dispatch-worker"


class RoleClass(StrEnum):
    """What kind of session carries a role, independently of its reach."""

    WORKER = "worker"
    STANDING = "standing"
    AGENT = "agent"


class RoleLabel(StrEnum):
    """The role's name in a caller-origin identity header (the closed label vocabulary)."""

    ORCHESTRATOR = "Orchestrator"
    INTEGRATOR = "Integrator"
    WORKER = "Worker"
    TASKER = "Tasker"
    JOB_RUNNER = "Job Runner"
    AGENT = "Agent"


class RoleName(StrEnum):
    """Closed vocabulary of the roles a session may carry."""

    BUILDER = "builder"
    REVIEWER = "reviewer"
    FINALIZER = "finalizer"
    DIAGNOSER = "diagnoser"
    DRIFT_ANALYZER = "drift-analyzer"
    ARTIST = "artist"
    FRONTENDER = "frontender"
    DEFERRER = "deferrer"
    PREPARE_ORCHESTRATOR = "prepare-orchestrator"
    WORK_ORCHESTRATOR = "work-orchestrator"
    CREATE_ORCHESTRATOR = "create-orchestrator"
    INTAKER = "intaker"
    ARCHITECT = "architect"
    PLANNER = "planner"
    INTEGRATOR = "integrator"
    COORDINATOR = "coordinator"
    TASK_PREPARER = "task-preparer"
    TASK_RUNNER = "task-runner"
    BUG_HUNTER = "bug-hunter"
    INSTALLATION_INSPECTOR = "installation-inspector"
    MEMORY_CURATOR = "memory-curator"
    DESK_MEMORY_CURATOR = "desk-memory-curator"
    HELPER = "helper"
    ONBOARDER = "onboarder"
    MAIL_TRIAGER = "mail-triager"


class LegacyRole(StrEnum):
    """The pre-catalog ``system_role`` values older nodes read for display and record alone."""

    WORKER = "worker"
    ORCHESTRATOR = "orchestrator"
    INTEGRATOR = "integrator"
    COORDINATOR = "coordinator"


@dataclass(frozen=True)
class Role:
    """One catalog entry: a role's class, reach and header label."""

    name: RoleName
    role_class: RoleClass
    full_reach: bool
    capabilities: frozenset[Capability]
    label: RoleLabel

    @property
    def legacy_projection(self) -> str:
        """The older ``system_role`` value this role projects as, derived from its class and reach.

        A worker-class role projects as ``worker``; the integrator and coordinator as themselves;
        any other full-reach role as ``orchestrator``; any other contained role as its own name.
        """
        if self.role_class is RoleClass.WORKER:
            return LegacyRole.WORKER
        if self.name is RoleName.INTEGRATOR:
            return LegacyRole.INTEGRATOR
        if self.name is RoleName.COORDINATOR:
            return LegacyRole.COORDINATOR
        if self.full_reach:
            return LegacyRole.ORCHESTRATOR
        return self.name


@dataclass(frozen=True)
class UnknownRole:
    """A recorded role the catalog does not name: a platform defect that grants nothing."""

    recorded: str


def _entry(
    name: RoleName,
    role_class: RoleClass,
    full_reach: bool,
    capabilities: frozenset[Capability],
    label: RoleLabel,
) -> tuple[RoleName, Role]:
    return name, Role(name, role_class, full_reach, capabilities, label)


# The set every worker-class role starts from. It holds no capability that observes the fleet or starts,
# revives, restarts or ends another session (``local/projects/teleclaude/spec/feature/identity/agent-roles``).
_WORKER_BASELINE: frozenset[Capability] = frozenset(
    {
        Capability.DOCS_READ,
        Capability.REMINDERS,
        Capability.TODO_READ,
        Capability.TODO_WRITE,
        Capability.ARTIFACT_READ,
        Capability.ARTIFACT_WRITE,
        Capability.STAMP,
        Capability.CODE,
        Capability.CODE_CHECK,
        Capability.MCP,
        Capability.PEER_TALK,
        Capability.SELF_ACTS,
        Capability.JOBS_READ,
        Capability.JOB_REPORT,
        Capability.OPERATION_READ,
        Capability.MESSAGING,
        Capability.MEMORIES_READ,
        Capability.CONFIG_READ,
    }
)

_CATALOG: dict[RoleName, Role] = dict(
    [
        _entry(
            RoleName.BUILDER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.REVIEWER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE | {Capability.TRANSCRIPT_READ},
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.FINALIZER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.DIAGNOSER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE | {Capability.TRANSCRIPT_READ},
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.DRIFT_ANALYZER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.ARTIST,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.FRONTENDER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.DEFERRER,
            RoleClass.WORKER,
            False,
            _WORKER_BASELINE,
            RoleLabel.WORKER,
        ),
        _entry(
            RoleName.PREPARE_ORCHESTRATOR,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.DISPATCH_WORKER,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.TRANSCRIPT_READ,
                    Capability.OPERATION_READ,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.WORK_ORCHESTRATOR,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.DISPATCH_WORKER,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.CREATE_ORCHESTRATOR,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.ARTIFACT_READ,
                    Capability.STAMP,
                    Capability.DISPATCH_WORKER,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.INTAKER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.PEER_TALK,
                    Capability.TRANSCRIPT_READ,
                    Capability.OPERATION_READ,
                    Capability.CODE,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.ARCHITECT,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.OPERATION_READ,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.PLANNER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_ORCHESTRATION,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.INTEGRATOR,
            RoleClass.STANDING,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.INTEGRATION,
                    Capability.MAINTENANCE_RECOVERY,
                    Capability.DISPATCH_WORKER,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.TRANSCRIPT_READ,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.STAMP,
                }
            ),
            RoleLabel.INTEGRATOR,
        ),
        _entry(
            RoleName.COORDINATOR,
            RoleClass.STANDING,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.SESSION_OBSERVE,
                    Capability.TRANSCRIPT_READ,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                }
            ),
            RoleLabel.ORCHESTRATOR,
        ),
        _entry(
            RoleName.TASK_PREPARER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.OPERATION_READ,
                }
            ),
            RoleLabel.TASKER,
        ),
        _entry(
            RoleName.TASK_RUNNER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_READ,
                    Capability.ARTIFACT_READ,
                    Capability.ARTIFACT_WRITE,
                    Capability.STAMP,
                    Capability.MESSAGING,
                }
            ),
            RoleLabel.TASKER,
        ),
        _entry(
            RoleName.BUG_HUNTER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.ARTIFACT_READ,
                    Capability.JOB_REPORT,
                    Capability.OPERATION_READ,
                }
            ),
            RoleLabel.JOB_RUNNER,
        ),
        _entry(
            RoleName.INSTALLATION_INSPECTOR,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.MAINTENANCE_RECOVERY,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.OPERATION_READ,
                }
            ),
            RoleLabel.INTEGRATOR,
        ),
        _entry(
            RoleName.MEMORY_CURATOR,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.MEMORY_CURATION,
                    Capability.SELF_ACTS,
                }
            ),
            RoleLabel.TASKER,
        ),
        _entry(
            RoleName.DESK_MEMORY_CURATOR,
            RoleClass.AGENT,
            False,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.MEMORY_CURATION,
                    Capability.SELF_ACTS,
                }
            ),
            RoleLabel.TASKER,
        ),
        _entry(
            RoleName.HELPER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                    Capability.STAMP,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.MCP,
                }
            ),
            RoleLabel.AGENT,
        ),
        _entry(
            RoleName.ONBOARDER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.CONFIG,
                    Capability.CONFIG_READ,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                    Capability.STAMP,
                }
            ),
            RoleLabel.AGENT,
        ),
        _entry(
            RoleName.MAIL_TRIAGER,
            RoleClass.AGENT,
            True,
            frozenset(
                {
                    Capability.DOCS_READ,
                    Capability.REMINDERS,
                    Capability.MESSAGING,
                    Capability.CODE,
                    Capability.CODE_CHECK,
                    Capability.STAMP,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                }
            ),
            RoleLabel.AGENT,
        ),
    ]
)


def resolve_role(name: str | None) -> Role | UnknownRole | None:
    """Resolve a session's recorded role to its catalog entry.

    ``None`` (no recorded role) is a human session and resolves to ``None``. A recorded value the
    catalog does not name resolves to ``UnknownRole``, which grants nothing.
    """
    if name is None:
        return None
    try:
        return _CATALOG[RoleName(name)]
    except ValueError:
        return UnknownRole(name)


def resolve_session_role(recorded: str | None, session_id: str | None) -> Role | UnknownRole | None:
    """Resolve a session's recorded role, reporting a value the catalog does not name as a platform defect."""
    resolved = resolve_role(recorded)
    if isinstance(resolved, UnknownRole):
        logger.error(_UNKNOWN_ROLE_LOG, session_id, recorded)
    return resolved


def legacy_system_role(recorded: str | None) -> str | None:
    """The older ``system_role`` value a recorded role projects as, for display on older readers.

    A session with no role, or a recorded value the catalog does not name, projects as nothing.
    """
    resolved = resolve_role(recorded)
    return resolved.legacy_projection if isinstance(resolved, Role) else None


def is_standing_session(recorded: str | None, *, scheduled: bool) -> bool:
    """Whether a session is standing: its work arrives from a queue, a schedule or the fleet.

    A session carrying a role of the standing class is standing, and so is a scheduled job's session
    whatever its role.
    """
    resolved = resolve_role(recorded)
    return scheduled or (isinstance(resolved, Role) and resolved.role_class is RoleClass.STANDING)


def is_worker_role(recorded: str | None) -> bool:
    """Whether a recorded role is of the worker class in the catalog; no role and an unnamed role are not."""
    resolved = resolve_role(recorded)
    return isinstance(resolved, Role) and resolved.role_class is RoleClass.WORKER


def catalog() -> tuple[Role, ...]:
    """Every catalog entry, in declaration order."""
    return tuple(_CATALOG.values())


def allows(role: Role, capability: Capability) -> bool:
    """Whether ``role`` reaches ``capability``: full reach, or membership in its explicit set."""
    return role.full_reach or capability in role.capabilities


def may_dispatch(caller: Role | None, target: Role) -> bool:
    """Whether ``caller`` may start a session carrying ``target``.

    A roleless caller (a human session) and a full-reach caller may start any role; a caller holding
    ``dispatch-worker`` may start a role of class ``worker``.
    """
    if caller is None or caller.full_reach:
        return True
    return allows(caller, Capability.DISPATCH_WORKER) and target.role_class is RoleClass.WORKER
