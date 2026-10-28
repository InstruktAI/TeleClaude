"""Agent role catalog: the one place a role's reach and class are composed.

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
    INSTALLATION = "installation"
    INSTALLATION_READ = "installation-read"
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
    MEMORIES_SAVE = "memories-save"
    DISPATCH_FOCUSED = "dispatch-focused"


class RoleClass(StrEnum):
    """What kind of session carries a role, independently of its reach."""

    FOCUSED = "focused"
    STANDING = "standing"
    AGENT = "agent"


class RoleName(StrEnum):
    """Closed vocabulary of the roles a session may carry."""

    BUILDER = "builder"
    REVIEWER = "reviewer"
    PRD_REVIEWER = "prd-reviewer"
    ARCHITECTURE_REVIEWER = "architecture-reviewer"
    PLAN_REVIEWER = "plan-reviewer"
    BUILD_REVIEWER = "build-reviewer"
    COMMIT_REVIEWER = "commit-reviewer"
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
    COMPANY_DESK_CURATOR = "company-desk-curator"
    PROJECT_DESK_CURATOR = "project-desk-curator"
    HELPER = "helper"
    COMPANY_ANALYST = "company-analyst"
    KNOWLEDGE_AUTHOR = "knowledge-author"
    PROJECT_ANALYST = "project-analyst"
    THIRD_PARTY_RESEARCHER = "third-party-researcher"
    ONBOARDER = "onboarder"
    CONFIG_ASSESSOR = "config-assessor"
    PROJECT_ONBOARDER = "project-onboarder"
    MAIL_TRIAGER = "mail-triager"


class LegacyRole(StrEnum):
    """The pre-catalog ``system_role`` values older nodes read for display and record alone."""

    WORKER = "worker"
    ORCHESTRATOR = "orchestrator"
    INTEGRATOR = "integrator"
    COORDINATOR = "coordinator"


@dataclass(frozen=True)
class Role:
    """One catalog entry: a role's class and reach."""

    name: RoleName
    role_class: RoleClass
    full_reach: bool
    capabilities: frozenset[Capability]

    @property
    def legacy_projection(self) -> str:
        """The older ``system_role`` value this role projects as, derived from its class and reach.

        A focused-class role projects as ``worker``; the integrator and coordinator as themselves;
        any other full-reach role as ``orchestrator``; any other contained role as its own name.
        """
        if self.role_class is RoleClass.FOCUSED:
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


# What every role holds beyond its own assignment: reading the installation's status never needs a grant.
_AGENT_BASELINE: frozenset[Capability] = frozenset({Capability.INSTALLATION_READ})


def _entry(
    name: RoleName,
    role_class: RoleClass,
    full_reach: bool,
    capabilities: frozenset[Capability],
) -> tuple[RoleName, Role]:
    return name, Role(name, role_class, full_reach, capabilities | _AGENT_BASELINE)


# The set every focused-class role starts from. It holds no capability that observes the fleet or starts,
# revives, restarts or ends another session, and sends to no other session: a focused session reports through
# its own output and artifacts (``local/projects/teleclaude/spec/feature/identity/agent-roles``).
_FOCUSED_BASELINE: frozenset[Capability] = frozenset(
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
        Capability.SELF_ACTS,
        Capability.OPERATION_READ,
    }
)

_CATALOG: dict[RoleName, Role] = dict(
    [
        _entry(
            RoleName.BUILDER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
        ),
        _entry(
            RoleName.REVIEWER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE | {Capability.TRANSCRIPT_READ},
        ),
        _entry(
            RoleName.FINALIZER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
        ),
        _entry(
            RoleName.DIAGNOSER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE | {Capability.TRANSCRIPT_READ},
        ),
        _entry(
            RoleName.DRIFT_ANALYZER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
        ),
        _entry(
            RoleName.ARTIST,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
        ),
        _entry(
            RoleName.FRONTENDER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
        ),
        _entry(
            RoleName.DEFERRER,
            RoleClass.FOCUSED,
            False,
            _FOCUSED_BASELINE,
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
                    Capability.DISPATCH_FOCUSED,
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
                    Capability.DISPATCH_FOCUSED,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                }
            ),
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
                    Capability.DISPATCH_FOCUSED,
                    Capability.SESSION_OBSERVE,
                    Capability.SESSION_ACT,
                    Capability.SELF_ACTS,
                    Capability.PEER_TALK,
                    Capability.OPERATION_READ,
                }
            ),
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
                    Capability.INSTALLATION,
                    Capability.DISPATCH_FOCUSED,
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
                    Capability.INSTALLATION,
                    Capability.TODO_READ,
                    Capability.TODO_WRITE,
                    Capability.OPERATION_READ,
                }
            ),
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
        ),
    ]
)

# Each procedure declares its own role. Procedures that need the same reach take it from one
# composite role, so each session still names its own assignment
# (``local/projects/teleclaude/spec/feature/identity/agent-roles``).
_COMPOSED_ROLES: dict[RoleName, tuple[RoleName, ...]] = {
    RoleName.REVIEWER: (
        RoleName.PRD_REVIEWER,
        RoleName.ARCHITECTURE_REVIEWER,
        RoleName.PLAN_REVIEWER,
        RoleName.BUILD_REVIEWER,
        RoleName.COMMIT_REVIEWER,
    ),
    RoleName.HELPER: (
        RoleName.COMPANY_ANALYST,
        RoleName.KNOWLEDGE_AUTHOR,
        RoleName.PROJECT_ANALYST,
        RoleName.THIRD_PARTY_RESEARCHER,
    ),
    RoleName.ONBOARDER: (RoleName.CONFIG_ASSESSOR, RoleName.PROJECT_ONBOARDER),
    RoleName.DESK_MEMORY_CURATOR: (RoleName.COMPANY_DESK_CURATOR, RoleName.PROJECT_DESK_CURATOR),
}
_CATALOG.update(
    _entry(member, base.role_class, base.full_reach, base.capabilities)
    for composite, members in _COMPOSED_ROLES.items()
    for base in (_CATALOG[composite],)
    for member in members
)

REVIEWER_ROLES: frozenset[RoleName] = frozenset({RoleName.REVIEWER, *_COMPOSED_ROLES[RoleName.REVIEWER]})


def composite_role(name: RoleName) -> RoleName:
    """The composite a procedure's own role takes its reach from, or the role itself."""
    return next((composite for composite, members in _COMPOSED_ROLES.items() if name in members), name)


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


def is_focused_role(recorded: str | None) -> bool:
    """Whether a recorded role is of the focused class in the catalog; no role and an unnamed role are not."""
    resolved = resolve_role(recorded)
    return isinstance(resolved, Role) and resolved.role_class is RoleClass.FOCUSED


def is_orchestrator_role(recorded: str | None) -> bool:
    """Whether a recorded role orchestrates todo work: the catalog assigns it todo orchestration explicitly.

    The lifecycle orchestrators hold it; the integrator, the coordinator, and every role whose reach
    merely covers it do not. No role and an unnamed role are not orchestrators.
    """
    resolved = resolve_role(recorded)
    return isinstance(resolved, Role) and Capability.TODO_ORCHESTRATION in resolved.capabilities


def catalog() -> tuple[Role, ...]:
    """Every catalog entry, in declaration order."""
    return tuple(_CATALOG.values())


# Capabilities every role reaches without composing them, so they stay out of every focused set.
_EVERY_ROLE: frozenset[Capability] = frozenset({Capability.MEMORIES_SAVE})


def allows(role: Role, capability: Capability) -> bool:
    """Whether ``role`` reaches ``capability``: full reach, every-role reach, or membership in its explicit set."""
    return role.full_reach or capability in _EVERY_ROLE or capability in role.capabilities


def may_dispatch(caller: Role | None, target: Role) -> bool:
    """Whether ``caller`` may start a session carrying ``target``.

    A roleless caller (a human session) and a full-reach caller may start any role; a caller holding
    ``dispatch-focused`` may start a role of class ``focused``.
    """
    if caller is None or caller.full_reach:
        return True
    return allows(caller, Capability.DISPATCH_FOCUSED) and target.role_class is RoleClass.FOCUSED
