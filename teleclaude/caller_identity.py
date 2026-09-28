"""Dependency-light caller identity rules shared by the CLI and daemon."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, assert_never

from teleclaude.config_roster import (
    CompanyMember,
    CompanyRole,
    PersonEntry,
    load_people_roster,
    load_person_memberships,
    project_ownership_for_path,
    project_ownership_for_slug,
)
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLES,
    ROLE_INTEGRATOR,
    ROLE_JOB_RUNNER,
    ROLE_ORCHESTRATOR,
    ROLE_SYSTEM,
    ROLE_TASKER,
    ROLE_WORKER,
    SYSTEM_DAEMON_PRINCIPAL,
    JobRole,
    SystemRole,
)
from teleclaude.snippet_scope import SnippetScope
from teleclaude.types.creation_record import EntryPoint

_HUMAN_PRINCIPAL_PREFIX = "human:"
_SYSTEM_PRINCIPAL_PREFIX = "system:"


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


type RoleScope = PlatformScope | CompanyScope | ProjectScope | PersonScope | SharedDocsScope


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


type RoleTarget = ProjectPath | Project | Company | Person | SessionOf | DocsTier | OperationOf | Platform


_UNKNOWN_ROLE_SCOPE_ERROR = "Unknown role scope: {scope}"


class CliResolvedIdentityFields(Protocol):
    """Resolved identity facts the client serializes onto its daemon request."""

    @property
    def caller(self) -> CliCaller: ...

    @property
    def principal(self) -> str | None: ...

    @property
    def system_role(self) -> str | None: ...

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
    system_role: str | None
    caller: CliCaller


def load_person_role_facts(person_slug: str, platform_role: str | None) -> PersonRoleFacts:
    """Load the role declarations identity uses to resolve one person's scope."""
    return PersonRoleFacts(
        person_slug=person_slug,
        platform_role=platform_role,
        memberships=load_person_memberships(person_slug),
    )


def scope_for_path(path: Path) -> RoleScope:
    """Resolve a filesystem path to its registered project scope or platform scope."""
    ownership = project_ownership_for_path(path)
    if ownership is None:
        return PlatformScope()
    return ProjectScope(project=ownership.project_slug, owner=ownership.company)


def scope_for_project(project_slug: str) -> RoleScope:
    """Resolve a project slug to its registered project scope or platform scope."""
    ownership = project_ownership_for_slug(project_slug)
    if ownership is None:
        return PlatformScope()
    return ProjectScope(project=ownership.project_slug, owner=ownership.company)


def scope_for_docs_tier(tier: DocsTier) -> RoleScope:
    """Resolve a documentation tier's own scope and qualified owner."""
    if tier.tier is SnippetScope.GLOBAL:
        return SharedDocsScope()
    if tier.tier is SnippetScope.COMPANY and tier.owner is not None:
        return CompanyScope(tier.owner)
    if tier.tier is SnippetScope.PROJECT and tier.owner is not None:
        return scope_for_project(tier.owner)
    if tier.tier is SnippetScope.PERSON and tier.owner is not None:
        return PersonScope(tier.owner)
    return PlatformScope()


def effective_role(facts: PersonRoleFacts, scope: RoleScope) -> str:
    """Return the highest declared role held at a scope containing the object."""
    candidates: list[str] = []
    if facts.platform_role is not None:
        candidates.append(facts.platform_role)

    if isinstance(scope, CompanyScope):
        member = facts.memberships.get(scope.company)
        if member is not None:
            candidates.append(member.role.value)
    elif isinstance(scope, ProjectScope) and scope.owner is not None:
        member = facts.memberships.get(scope.owner)
        if member is not None and (member.role is CompanyRole.ADMIN or scope.project in member.projects):
            candidates.append(member.role.value)
    elif isinstance(scope, SharedDocsScope):
        candidates.extend(member.role.value for member in facts.memberships.values())
    elif isinstance(scope, PersonScope) and scope.person == facts.person_slug:
        candidates.append(HUMAN_ROLE_ADMIN)
    elif not isinstance(scope, PlatformScope):
        raise TypeError(_UNKNOWN_ROLE_SCOPE_ERROR.format(scope=scope))

    recognized = [role for role in candidates if role in HUMAN_ROLES]
    if not recognized:
        return HUMAN_ROLE_CUSTOMER
    return min(recognized, key=HUMAN_ROLES.index)


def _scope_for_target(target: RoleTarget) -> RoleScope:
    """Resolve an operation target to the object's own registered scope."""
    match target:
        case ProjectPath(path=path):
            return scope_for_path(path)
        case Project(project_slug=project_slug):
            return scope_for_project(project_slug)
        case Company(company=company):
            return CompanyScope(company)
        case Person(person_slug=person_slug):
            return PersonScope(person_slug)
        case SessionOf(project_path=project_path):
            return PlatformScope() if project_path is None else scope_for_path(Path(project_path))
        case DocsTier():
            return scope_for_docs_tier(target)
        case OperationOf(cwd=cwd):
            return PlatformScope() if cwd is None else scope_for_path(cwd)
        case Platform():
            return PlatformScope()
        case _:
            return assert_never(target)


class RoleResolver:
    """Resolve object roles while reusing one caller's facts per request."""

    def __init__(self) -> None:
        self._facts_by_person: dict[str, PersonRoleFacts] = {}

    def role_for(self, caller: CliCaller | None, target: RoleTarget) -> str:
        """Resolve the caller's effective person role for the target object."""
        if not isinstance(caller, PersonCliCaller) or not caller.person_slug:
            return HUMAN_ROLE_CUSTOMER
        facts = self._facts_by_person.get(caller.person_slug)
        if facts is None:
            facts = load_person_role_facts(caller.person_slug, caller.human_role)
            self._facts_by_person[caller.person_slug] = facts
        return effective_role(facts, _scope_for_target(target))


_CARRIED_IDENTITY_HEADERS = (
    ("session_id", "x-caller-session-id"),
    ("principal", "x-caller-principal"),
    ("system_role", "x-caller-system-role"),
    ("human_role", "x-caller-human-role"),
    ("email", "x-caller-email"),
    ("entry_point", "x-caller-entry-point"),
    ("company", "x-caller-company"),
)


@dataclass(frozen=True)
class CarriedIdentity:
    """Frozen identity payload shared by clients and the daemon request edge."""

    session_id: str | None = None
    principal: str | None = None
    system_role: str | None = None
    human_role: str | None = None
    email: str | None = None
    entry_point: str | None = None
    company: str | None = None

    @classmethod
    def from_cli_identity(cls, identity: CliResolvedIdentityFields) -> CarriedIdentity:
        """Adapt the gate's resolved caller into the carried request shape."""
        return cls(
            session_id=identity.session_id,
            principal=identity.principal,
            system_role=identity.system_role,
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
            system_role=identity.system_role,
            human_role=identity.caller.human_role,
            email=identity.caller.email,
            entry_point=EntryPoint.AGENT.value,
            company=company,
        )

    @classmethod
    def from_session_facts(cls, session: SessionIdentityFields) -> CarriedIdentity:
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
    def system_role(self) -> str | None: ...

    @property
    def working_slug(self) -> str | None: ...

    @property
    def job(self) -> str | None: ...

    @property
    def company(self) -> str | None: ...


def resolve_session_principal(session: SessionIdentityFields) -> tuple[str, str]:
    """Resolve the canonical principal and informational role for a session."""
    if session.principal:
        return session.principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.human_email:
        principal = f"{_HUMAN_PRINCIPAL_PREFIX}{session.human_email}"
        return principal, session.human_role or HUMAN_ROLE_CUSTOMER
    if session.system_role:
        return SYSTEM_DAEMON_PRINCIPAL, session.system_role
    raise SessionIdentityError(
        f"Session {session.session_id} has no identity: no principal, no human_email, no system_role. "
        "Authentication required."
    )


def caller_from_principal(principal: str | None) -> CliCaller:
    """Resolve a carried principal against the lightweight people roster."""
    if not principal:
        return NoIdentityCliCaller()
    if principal.startswith(_HUMAN_PRINCIPAL_PREFIX):
        email = principal.removeprefix(_HUMAN_PRINCIPAL_PREFIX)
        if not email:
            return NoIdentityCliCaller()
        person = person_entry_for_email(email)
        return PersonCliCaller(
            email=email,
            person_slug=person.slug if person is not None else None,
            human_role=_normalize_human_role(person.role) if person is not None else None,
        )
    if principal.startswith(_SYSTEM_PRINCIPAL_PREFIX) and principal.removeprefix(_SYSTEM_PRINCIPAL_PREFIX):
        return SystemCliCaller()
    return NoIdentityCliCaller()


def _normalize_human_role(role: str | None) -> str:
    """Normalize unknown configured human roles to the customer role."""
    return role if role in HUMAN_ROLES else HUMAN_ROLE_CUSTOMER


def derive_session_system_role(session: SessionIdentityFields) -> str | None:
    """Derive system role from authoritative session fields."""
    if session.job == JobRole.COORDINATOR.value:
        return SystemRole.COORDINATOR
    if session.system_role:
        normalized = session.system_role.strip().lower()
        if normalized in {
            ROLE_WORKER,
            ROLE_SYSTEM,
            ROLE_INTEGRATOR,
            SystemRole.COORDINATOR,
            ROLE_ORCHESTRATOR,
            ROLE_TASKER,
            ROLE_JOB_RUNNER,
        }:
            return normalized
    if session.working_slug:
        return ROLE_WORKER
    return None


def identity_for_session(session: SessionIdentityFields) -> SessionIdentity:
    """Resolve one session record into its CLI caller and role facts."""
    try:
        principal, principal_role = resolve_session_principal(session)
    except SessionIdentityError:
        principal, principal_role = None, None
        caller: CliCaller = NoIdentityCliCaller()
    else:
        caller = caller_from_principal(principal)
        if isinstance(caller, NoIdentityCliCaller):
            principal, principal_role = None, None
    return SessionIdentity(
        principal=principal,
        principal_role=principal_role,
        system_role=derive_session_system_role(session),
        caller=caller,
    )


def authorizing_role(caller: CliCaller, system_role: str | None, target: RoleTarget) -> str | None:
    """Return the role that authorizes a caller at the target object."""
    if isinstance(caller, PersonCliCaller):
        return RoleResolver().role_for(caller, target)
    if isinstance(caller, SystemCliCaller):
        return system_role
    return None


def session_act_exception(
    act: SessionAct,
    caller_session_id: str | None,
    caller_initiator_session_id: str | None,
    caller_system_role: str | None,
    target_session_id: str | None,
) -> bool | None:
    """Apply self-end and self-restart exceptions before the declared band."""
    if caller_session_id is None or target_session_id != caller_session_id:
        if act is SessionAct.RESTART and caller_system_role == ROLE_WORKER:
            return False
        return None
    if act is SessionAct.END and caller_initiator_session_id is not None:
        return None
    return True


def human_principal_for_email(email: str) -> str:
    """Build the canonical principal for a verified person email."""
    return f"{_HUMAN_PRINCIPAL_PREFIX}{email}"


def person_entry_for_email(email: str) -> PersonEntry | None:
    """Return the roster entry for one email, if it is registered."""
    matches = person_entries_for_email(email)
    return matches[-1] if matches else None


def person_entries_for_email(email: str) -> list[PersonEntry]:
    """Return every valid roster entry matching an email, preserving roster order."""
    normalized = email.strip().lower()
    return [entry for entry in load_people_roster() if entry.email.lower() == normalized]
