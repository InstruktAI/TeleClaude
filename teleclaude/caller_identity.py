"""Dependency-light caller identity rules shared by the CLI and daemon."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, assert_never

from teleclaude.agent_registry import LaunchProfile
from teleclaude.config.identity_schema import CompanyMember, CompanyRole, PersonEntry
from teleclaude.config.loader import company_memberships, load_global_config
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLES,
    SYSTEM_DAEMON_PRINCIPAL,
)
from teleclaude.core.roles import Role, RoleClass, resolve_role
from teleclaude.services.project_catalog.ownership import ProjectOwnershipIndex, load_project_ownership_index
from teleclaude.snippet_scope import SnippetScope
from teleclaude.types.creation_record import EntryPoint

HUMAN_PRINCIPAL_PREFIX = "human:"
SYSTEM_PRINCIPAL_PREFIX = "system:"
VISITOR_PRINCIPAL_PREFIX = "visitor:"
TELEC_COMMAND_PREFIX = "telec "


class SessionIdentityError(ValueError):
    """Raised when a session has no resolvable identity."""


class CliCallerKind(StrEnum):
    """Kinds of identity a local CLI caller can carry."""

    PERSON = "person"
    SYSTEM = "system"
    NONE = "none"


class SessionAct(StrEnum):
    """Session commands with a caller-owned self-target exception."""

    END = "end"
    RESTART = "restart"
    SHOW = "show"


class RelayedAct(StrEnum):
    """Caller-facing CLI verbs whose target computer makes the person decision."""

    START = "telec sessions start"
    RUN = "telec sessions run"
    SEND = "telec sessions send"
    TAIL = "telec sessions tail"
    END = "telec sessions end"
    REVIVE = "telec sessions revive"
    RESTART = "telec sessions restart"
    UNSUBSCRIBE = "telec sessions unsubscribe"
    LIST = "telec sessions list"
    SHOW = "telec sessions show"
    OPERATIONS_GET = "telec operations get"
    HISTORY_SEARCH = "telec history search"
    HISTORY_SHOW = "telec history show"


@dataclass(frozen=True)
class PersonCliCaller:
    """A caller acting with a person's carried or terminal identity."""

    kind: Literal[CliCallerKind.PERSON] = CliCallerKind.PERSON
    email: str | None = None
    person_slug: str | None = None
    human_role: str | None = None


@dataclass(frozen=True)
class SystemCliCaller:
    """A caller acting with a system principal and no person role."""

    kind: Literal[CliCallerKind.SYSTEM] = CliCallerKind.SYSTEM
    email: None = None
    person_slug: None = None
    human_role: None = None


@dataclass(frozen=True)
class NoIdentityCliCaller:
    """A caller for which no person or system identity is available."""

    kind: Literal[CliCallerKind.NONE] = CliCallerKind.NONE
    email: None = None
    person_slug: None = None
    human_role: None = None


type CliCaller = PersonCliCaller | SystemCliCaller | NoIdentityCliCaller


@dataclass(frozen=True)
class PlatformScope:
    """The platform registry scope containing every platform object."""


@dataclass(frozen=True)
class CompanyScope:
    """One company's configuration and owned organizational lineage."""

    company: str


@dataclass(frozen=True)
class ProjectScope:
    """One registered project and its declared company owner, if any."""

    project: str
    owner: str | None


@dataclass(frozen=True)
class PersonScope:
    """One person's private configuration and documentation scope."""

    person: str


@dataclass(frozen=True)
class SharedDocsScope:
    """The platform's shared documentation inherited by every company."""


@dataclass(frozen=True)
class ThisComputerScope:
    """Objects held by this computer whose roles are resolved from its own registries."""


type RoleScope = PlatformScope | CompanyScope | ProjectScope | PersonScope | SharedDocsScope | ThisComputerScope


@dataclass(frozen=True)
class PersonRoleFacts:
    """The declared platform role and company memberships for one person."""

    person_slug: str
    platform_role: str | None
    memberships: Mapping[str, CompanyMember]


@dataclass(frozen=True)
class ProjectPath:
    """A filesystem path whose registered project determines its role scope."""

    path: Path


@dataclass(frozen=True)
class Project:
    """A registered project named by its canonical slug."""

    project_slug: str


@dataclass(frozen=True)
class Company:
    """A registered company named by its canonical slug."""

    company: str


@dataclass(frozen=True)
class Person:
    """A registered person named by their canonical slug."""

    person_slug: str


@dataclass(frozen=True)
class SessionOf:
    """A session whose project path is the object that determines its scope."""

    project_path: str | Path | None


@dataclass(frozen=True)
class DocsTier:
    """A documentation tier and, for qualified tiers, its owner slug."""

    tier: SnippetScope
    owner: str | None = None


@dataclass(frozen=True)
class OperationOf:
    """An operation whose working directory determines its project scope."""

    cwd: Path | None


@dataclass(frozen=True)
class Platform:
    """A platform-wide object with no narrower registered scope."""


@dataclass(frozen=True)
class ThisComputer:
    """Objects held by the computer making the current role decision."""


type RoleTarget = (
    ProjectPath | Project | Company | Person | SessionOf | DocsTier | OperationOf | Platform | ThisComputer
)


class CliResolvedIdentityFields(Protocol):
    """Resolved identity facts the client serializes onto its daemon request."""

    @property
    def caller(self) -> CliCaller: ...

    @property
    def principal(self) -> str | None: ...

    @property
    def role(self) -> str | None: ...

    @property
    def session_id(self) -> str | None: ...

    @property
    def entry_point(self) -> str | None: ...

    @property
    def company(self) -> str | None: ...


@dataclass(frozen=True)
class SessionIdentity:
    """Resolved principal, roles, and caller for one session record."""

    principal: str | None
    principal_role: str | None
    role: str | None
    caller: CliCaller


def load_person_role_facts(person_slug: str, platform_role: str | None) -> PersonRoleFacts:
    """Load the role declarations identity uses to resolve one person's scope."""
    return PersonRoleFacts(
        person_slug=person_slug,
        platform_role=platform_role,
        memberships=company_memberships(person_slug),
    )


def scope_for_path(path: Path, ownership_index: ProjectOwnershipIndex) -> RoleScope:
    """Resolve a filesystem path to its registered project scope or platform scope."""
    ownership = ownership_index.for_path(path)
    if ownership is None:
        return PlatformScope()
    return ProjectScope(project=ownership.project_slug, owner=ownership.company)


def scope_for_project(project_slug: str, ownership_index: ProjectOwnershipIndex) -> RoleScope:
    """Resolve a project slug to its registered project scope or platform scope."""
    ownership = ownership_index.for_slug(project_slug)
    if ownership is None:
        return PlatformScope()
    return ProjectScope(project=ownership.project_slug, owner=ownership.company)


def scope_for_docs_tier(
    tier: DocsTier,
    ownership_index: ProjectOwnershipIndex | None,
) -> RoleScope:
    """Resolve a documentation tier's own scope and qualified owner."""
    if tier.tier is SnippetScope.GLOBAL:
        return SharedDocsScope()
    if tier.tier is SnippetScope.COMPANY and tier.owner is not None:
        return CompanyScope(tier.owner)
    if tier.tier is SnippetScope.PROJECT and tier.owner is not None:
        assert ownership_index is not None
        return scope_for_project(tier.owner, ownership_index)
    if tier.tier is SnippetScope.PERSON and tier.owner is not None:
        return PersonScope(tier.owner)
    return PlatformScope()


def effective_role(facts: PersonRoleFacts, scope: RoleScope) -> str:
    """Return the highest declared role held at a scope containing the object."""
    candidates: list[str] = []
    if facts.platform_role is not None:
        candidates.append(facts.platform_role)

    match scope:
        case PlatformScope():
            pass
        case CompanyScope(company=company):
            member = facts.memberships.get(company)
            if member is not None:
                candidates.append(member.role.value)
        case ProjectScope(project=project, owner=owner):
            if owner is not None:
                member = facts.memberships.get(owner)
                if member is not None and (member.role is CompanyRole.ADMIN or project in member.projects):
                    candidates.append(member.role.value)
        case SharedDocsScope() | ThisComputerScope():
            return _effective_platform_and_company_role(facts)
        case PersonScope(person=person):
            if person == facts.person_slug:
                candidates.append(HUMAN_ROLE_ADMIN)
        case _:
            return assert_never(scope)

    return _highest_ranked_role(candidates)


def _effective_platform_and_company_role(facts: PersonRoleFacts) -> str:
    """Resolve the highest role this computer can establish for a person."""
    candidates = [member.role.value for member in facts.memberships.values()]
    if facts.platform_role is not None:
        candidates.append(facts.platform_role)
    return _highest_ranked_role(candidates)


def _highest_ranked_role(candidates: list[str]) -> str:
    """Return the highest recognized role among the declared candidates."""
    recognized = [role for role in candidates if role in HUMAN_ROLES]
    if not recognized:
        return HUMAN_ROLE_CUSTOMER
    return min(recognized, key=HUMAN_ROLES.index)


def _scope_for_target(target: RoleTarget, ownership_index: ProjectOwnershipIndex | None) -> RoleScope:
    """Resolve an operation target to the object's own registered scope."""
    match target:
        case ProjectPath(path=path):
            assert ownership_index is not None
            return scope_for_path(path, ownership_index)
        case Project(project_slug=project_slug):
            assert ownership_index is not None
            return scope_for_project(project_slug, ownership_index)
        case Company(company=company):
            return CompanyScope(company)
        case Person(person_slug=person_slug):
            return PersonScope(person_slug)
        case SessionOf(project_path=project_path):
            if project_path is None:
                return PlatformScope()
            assert ownership_index is not None
            return scope_for_path(Path(project_path), ownership_index)
        case DocsTier():
            return scope_for_docs_tier(target, ownership_index)
        case OperationOf(cwd=cwd):
            if cwd is None:
                return PlatformScope()
            assert ownership_index is not None
            return scope_for_path(cwd, ownership_index)
        case Platform():
            return PlatformScope()
        case ThisComputer():
            return ThisComputerScope()
        case _:
            return assert_never(target)


class RoleResolver:
    """Resolve object roles while reusing caller facts and target scopes per request."""

    def __init__(self) -> None:
        self._facts_by_person: dict[str, PersonRoleFacts] = {}
        self._project_ownership_index: ProjectOwnershipIndex | None = None
        self._scopes_by_target: dict[RoleTarget, RoleScope] = {}

    def role_for(self, caller: CliCaller | None, target: RoleTarget) -> str:
        """Resolve the caller's effective person role for the target object."""
        if not isinstance(caller, PersonCliCaller) or not caller.person_slug:
            return HUMAN_ROLE_CUSTOMER
        facts = self._facts_for(caller)
        scope = self._scopes_by_target.get(target)
        if scope is None:
            if _target_uses_project_ownership(target):
                self._ownership_index()
            scope = _scope_for_target(target, self._project_ownership_index)
            self._scopes_by_target[target] = scope
        return effective_role(facts, scope)

    def _facts_for(self, caller: PersonCliCaller) -> PersonRoleFacts:
        """Return cached authorization facts for one person caller."""
        assert caller.person_slug is not None
        facts = self._facts_by_person.get(caller.person_slug)
        if facts is None:
            facts = load_person_role_facts(caller.person_slug, caller.human_role)
            self._facts_by_person[caller.person_slug] = facts
        return facts

    def _ownership_index(self) -> ProjectOwnershipIndex:
        """Return this request's cached project ownership snapshot."""
        if self._project_ownership_index is None:
            self._project_ownership_index = load_project_ownership_index()
        return self._project_ownership_index


def _target_uses_project_ownership(target: RoleTarget) -> bool:
    """Identify targets whose scope comes from the registered project roots."""
    match target:
        case ProjectPath() | Project():
            return True
        case SessionOf(project_path=project_path):
            return project_path is not None
        case DocsTier(tier=SnippetScope.PROJECT, owner=owner):
            return owner is not None
        case OperationOf(cwd=cwd):
            return cwd is not None
        case _:
            return False


_CARRIED_IDENTITY_HEADERS = (
    ("session_id", "x-caller-session-id"),
    ("principal", "x-caller-principal"),
    ("role", "x-caller-role"),
    ("human_role", "x-caller-human-role"),
    ("email", "x-caller-email"),
    ("entry_point", "x-caller-entry-point"),
    ("company", "x-caller-company"),
    ("command", "x-caller-command"),
)


@dataclass(frozen=True)
class CarriedIdentity:
    """Frozen identity payload shared by clients and the daemon request edge."""

    session_id: str | None = None
    principal: str | None = None
    role: str | None = None
    human_role: str | None = None
    email: str | None = None
    entry_point: str | None = None
    company: str | None = None
    command: str | None = None

    def with_command(self, command_path: str | None) -> CarriedIdentity:
        """Carry the CLI command the caller was cleared as; absent when no command was cleared."""
        return replace(self, command=cleared_command_path(command_path) if command_path else None)

    @classmethod
    def from_cli_identity(cls, identity: CliResolvedIdentityFields) -> CarriedIdentity:
        """Adapt the gate's resolved caller into the carried request shape."""
        return cls(
            session_id=identity.session_id,
            principal=identity.principal,
            role=identity.role,
            human_role=identity.caller.human_role,
            email=identity.caller.email,
            entry_point=identity.entry_point,
            company=identity.company if identity.session_id is not None else None,
        )

    @classmethod
    def from_session_identity(
        cls,
        session_id: str,
        identity: SessionIdentity,
        *,
        company: str | None,
    ) -> CarriedIdentity:
        """Carry the session that owns an in-daemon operation context."""
        return cls(
            session_id=session_id,
            principal=identity.principal,
            role=identity.role,
            human_role=identity.caller.human_role,
            email=identity.caller.email,
            entry_point=EntryPoint.AGENT.value,
            company=company,
        )

    @classmethod
    def from_session_facts(cls, session: ConfinedSessionIdentityFields) -> CarriedIdentity:
        """Resolve persisted session facts through the shared identity rule."""
        resolved = identity_for_session(session)
        return cls.from_session_identity(session.session_id, resolved, company=session.company)

    def to_headers(self) -> dict[str, str]:
        """Encode each present identity fact under its canonical wire header."""
        return {
            header: value
            for attribute, header in _CARRIED_IDENTITY_HEADERS
            if (value := getattr(self, attribute)) is not None
        }

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> CarriedIdentity:
        """Decode the identity headers while ignoring unrelated request headers."""
        normalized = {name.lower(): value for name, value in headers.items()}
        fields = {attribute: normalized.get(header) for attribute, header in _CARRIED_IDENTITY_HEADERS}
        return cls(**fields)


class SessionIdentityFields(Protocol):
    """The persisted fields consumed by caller resolution."""

    @property
    def session_id(self) -> str: ...

    @property
    def project_path(self) -> str | None: ...

    @property
    def principal(self) -> str | None: ...

    @property
    def human_email(self) -> str | None: ...

    @property
    def human_role(self) -> str | None: ...

    @property
    def role(self) -> str | None: ...

    @property
    def working_slug(self) -> str | None: ...

    @property
    def job(self) -> str | None: ...

    @property
    def company(self) -> str | None: ...


class ConfinedSessionIdentityFields(SessionIdentityFields, Protocol):
    """Session facts plus the launch confinement recorded when the session was created."""

    @property
    def confinement_profile(self) -> str | None: ...


def is_desk_role(role: str | None, human_role: str | None) -> bool:
    """Whether a session's persisted roles place it at a help desk under desk confinement.

    A session with no agent role whose recorded person role is below member
    (customer) is placed at the help desk and runs
    confined there.
    """
    return role is None and human_role is not None and human_role not in (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER)


def is_desk_visitor(caller: CliCaller) -> bool:
    """Whether a caller is an anonymous help-desk visitor: a customer with no person identity."""
    return isinstance(caller, PersonCliCaller) and caller.email is None and caller.person_slug is None


def _desk_visitor_caller(session: ConfinedSessionIdentityFields) -> CliCaller:
    """Resolve a principal-less session to the anonymous desk visitor, or to no identity."""
    if (
        session.role is None
        and session.human_role == HUMAN_ROLE_CUSTOMER
        and session.confinement_profile == LaunchProfile.HELP_DESK
    ):
        return PersonCliCaller(human_role=HUMAN_ROLE_CUSTOMER)
    return NoIdentityCliCaller()


def resolve_session_principal(session: SessionIdentityFields) -> tuple[str, str]:
    """Resolve the canonical principal and informational role for a session."""
    if session.principal:
        return session.principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.human_email:
        principal = f"{HUMAN_PRINCIPAL_PREFIX}{session.human_email}"
        return principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.role:
        return SYSTEM_DAEMON_PRINCIPAL, session.role
    raise SessionIdentityError(
        f"Session {session.session_id} has no identity: no principal, no human_email, no role. Authentication required."
    )


def caller_from_principal(principal: str | None) -> CliCaller:
    """Resolve a carried principal against the lightweight people roster."""
    if not principal:
        return NoIdentityCliCaller()
    if principal.startswith(HUMAN_PRINCIPAL_PREFIX):
        email = principal.removeprefix(HUMAN_PRINCIPAL_PREFIX)
        if not email:
            return NoIdentityCliCaller()
        person = person_entry_for_email(email)
        return PersonCliCaller(
            email=email,
            person_slug=person.slug if person is not None else None,
            human_role=_normalize_human_role(person.role) if person is not None else None,
        )
    if principal.startswith(SYSTEM_PRINCIPAL_PREFIX) and principal.removeprefix(SYSTEM_PRINCIPAL_PREFIX):
        return SystemCliCaller()
    return NoIdentityCliCaller()


def _normalize_human_role(role: str | None) -> str:
    """Normalize unknown configured human roles to the customer role."""
    return role if role in HUMAN_ROLES else HUMAN_ROLE_CUSTOMER


def identity_for_session(session: ConfinedSessionIdentityFields) -> SessionIdentity:
    """Resolve one session record into its CLI caller and role facts.

    A session with no principal, email or system role is the anonymous desk
    visitor when it was created confined at a help desk with the customer
    role; any other principal-less session carries no identity.
    """
    try:
        principal, principal_role = resolve_session_principal(session)
    except SessionIdentityError:
        principal, principal_role = None, None
        caller: CliCaller = _desk_visitor_caller(session)
    else:
        caller = caller_from_principal(principal)
        if isinstance(caller, NoIdentityCliCaller):
            principal, principal_role = None, None
    return SessionIdentity(
        principal=principal,
        principal_role=principal_role,
        role=session.role or None,
        caller=caller,
    )


def authorizing_role(caller: CliCaller, role: str | None, target: RoleTarget) -> str | None:
    """Return the role that authorizes a caller at the target object."""
    if isinstance(caller, PersonCliCaller):
        return RoleResolver().role_for(caller, target)
    if isinstance(caller, SystemCliCaller):
        return role
    return None


def session_act_exception(
    act: SessionAct,
    caller_session_id: str | None,
    caller_initiator_session_id: str | None,
    caller_role: str | None,
    target_session_id: str | None,
) -> bool | None:
    """Apply self-end, self-restart, and self-show exceptions before the declared band."""
    if caller_session_id is None or target_session_id != caller_session_id:
        resolved_caller_role = resolve_role(caller_role)
        is_focused = isinstance(resolved_caller_role, Role) and resolved_caller_role.role_class is RoleClass.FOCUSED
        if act is SessionAct.RESTART and is_focused:
            return False
        return None
    if act is SessionAct.END and caller_initiator_session_id is not None:
        return None
    return True


def cleared_command_path(command_path: str) -> str:
    """The canonical wire form of a CLI command path a caller was cleared as."""
    path = command_path.strip()
    return path if path.startswith(TELEC_COMMAND_PREFIX) else f"{TELEC_COMMAND_PREFIX}{path}"


def human_principal_for_email(email: str) -> str:
    """Build the canonical principal for a verified person email."""
    return f"{HUMAN_PRINCIPAL_PREFIX}{email}"


def visitor_principal(identity_key: str) -> str:
    """Build the principal an unregistered visitor's records are kept under, from the platform identity they wrote from."""
    return f"{VISITOR_PRINCIPAL_PREFIX}{identity_key}"


def person_entry_for_email(email: str) -> PersonEntry | None:
    """Return the roster entry for one email, if it is registered."""
    matches = person_entries_for_email(email)
    return matches[-1] if matches else None


def person_entries_for_email(email: str) -> list[PersonEntry]:
    """Return every valid roster entry matching an email, preserving roster order."""
    return entries_for_email(load_global_config().people, email)


def entries_for_email(entries: Sequence[PersonEntry], email: str) -> list[PersonEntry]:
    """Return supplied roster entries matching an email, preserving roster order."""
    normalized = email.strip().lower()
    return [entry for entry in entries if entry.email.strip().lower() == normalized]
