"""Resolution of declared company memberships and project assignments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import resolve_session_principal
from teleclaude.config.identity_schema import CompanyRole, PersonEntry
from teleclaude.config.loader import (
    company_memberships,
    find_company_config_path,
    load_company_config,
    load_global_config,
    load_person_config_for_entry,
)
from teleclaude.config.schema import PersonConfig
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.paths import PEOPLE_DIR
from teleclaude.services.project_catalog import get_project_catalog_service

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_ORGANIZATION_RESOLVED_EVENT = "organization_resolved"
_ORGANIZATION_STALE_ASSIGNMENT_EVENT = "organization_stale_assignment"
_PLATFORM_ADMIN_UNREADABLE_EVENT = "platform_admin_config_unreadable"


@dataclass(frozen=True)
class CompanyMembership:
    """One declared company role for a person."""

    company_slug: str
    role: CompanyRole


@dataclass(frozen=True)
class ProjectRef:
    """One project associated with a company."""

    company_slug: str
    project_slug: str


@dataclass(frozen=True)
class StaleAssignment:
    """An assignment retained by a former project-owning company."""

    company_slug: str
    project_slug: str
    current_owner: str | None


@dataclass(frozen=True)
class OrganizationalMembership:
    """The separate declared, derived, and stale facts resolved for one person."""

    memberships: tuple[CompanyMembership, ...]
    assignments: tuple[ProjectRef, ...]
    covered: tuple[ProjectRef, ...]
    stale: tuple[StaleAssignment, ...]


class PersonRoleEntry(TypedDict, total=False):
    """One read-only platform or company role projection for a person."""

    platform: str
    company: str
    role: str
    projects: list[str]


def resolve_organization(person_slug: str) -> OrganizationalMembership:
    """Resolve a person's declared company roles and current project relationships."""
    projects = {project.slug: project for project in get_project_catalog_service().list_projects()}
    memberships: list[CompanyMembership] = []
    assignments: list[ProjectRef] = []
    covered: list[ProjectRef] = []
    stale: list[StaleAssignment] = []
    for company_slug, member in company_memberships(person_slug).items():
        memberships.append(CompanyMembership(company_slug=company_slug, role=member.role))
        if member.role is CompanyRole.ADMIN:
            covered.extend(
                ProjectRef(company_slug=company_slug, project_slug=project.slug)
                for project in projects.values()
                if project.config.company == company_slug
            )
        for project_slug in member.projects:
            project = projects.get(project_slug)
            current_owner = project.config.company if project is not None else None
            if current_owner == company_slug:
                assignments.append(ProjectRef(company_slug=company_slug, project_slug=project_slug))
            else:
                stale_assignment = StaleAssignment(
                    company_slug=company_slug,
                    project_slug=project_slug,
                    current_owner=current_owner,
                )
                stale.append(stale_assignment)
                logger.info(
                    _ORGANIZATION_STALE_ASSIGNMENT_EVENT,
                    person=person_slug,
                    company=stale_assignment.company_slug,
                    project=stale_assignment.project_slug,
                    current_owner=stale_assignment.current_owner,
                )
    result = OrganizationalMembership(
        memberships=tuple(sorted(memberships, key=lambda membership: membership.company_slug)),
        assignments=tuple(
            sorted(assignments, key=lambda assignment: (assignment.company_slug, assignment.project_slug))
        ),
        covered=tuple(sorted(covered, key=lambda project: (project.company_slug, project.project_slug))),
        stale=tuple(sorted(stale, key=lambda assignment: (assignment.company_slug, assignment.project_slug))),
    )
    logger.info(
        _ORGANIZATION_RESOLVED_EVENT,
        person=person_slug,
        memberships=len(result.memberships),
        assignments=len(result.assignments),
        covered=len(result.covered),
        stale=len(result.stale),
    )
    return result


def platform_admin_people() -> list[tuple[str, PersonConfig]]:
    """Each platform admin's slug and person configuration, from the global roster.

    An admin whose person configuration cannot be read is left out and logged.
    """
    admins: list[tuple[str, PersonConfig]] = []
    for person in load_global_config().people:
        if person.role != HUMAN_ROLE_ADMIN:
            continue
        slug = person.slug or person.name
        try:
            person_config = load_person_config_for_entry(person, PEOPLE_DIR)
        except (OSError, ValueError) as exc:
            logger.warning(_PLATFORM_ADMIN_UNREADABLE_EVENT, person=slug, error=str(exc))
            continue
        if person_config is not None:
            admins.append((slug, person_config))
    return admins


def platform_admin_roster() -> list[PersonEntry]:
    """Return every platform admin declared on the people roster."""
    return [person for person in load_global_config().people if person.role == HUMAN_ROLE_ADMIN]


def company_admin_slugs(company_slug: str, companies_root: Path | None = None) -> list[str]:
    """The admins on a company's roster, in slug order; none when the company is unknown."""
    declaration = find_company_config_path(company_slug, companies_root)
    if declaration is None:
        return []
    company = load_company_config(declaration)
    return sorted(slug for slug, member in company.members.items() if member.role is CompanyRole.ADMIN)


def company_project_slugs(company_slug: str) -> list[str]:
    """The registered projects whose own declaration names ``company_slug`` as owner, in slug order."""
    return sorted(
        project.slug
        for project in get_project_catalog_service().list_projects()
        if project.config.company == company_slug
    )


def company_role(person_slug: str, company_slug: str) -> str | None:
    """Return a person's declared role in one company, if they belong to it."""
    membership = next(
        (item for item in resolve_organization(person_slug).memberships if item.company_slug == company_slug),
        None,
    )
    return membership.role.value if membership is not None else None


def person_roles(person_slug: str) -> list[PersonRoleEntry]:
    """Project a person's declared platform and company roles for read-only config views."""
    person = next((entry for entry in load_global_config().people if entry.slug == person_slug), None)
    roles: list[PersonRoleEntry] = []
    if person is not None and person.role is not None:
        roles.append({"platform": person.role})

    organization = resolve_organization(person_slug)
    assignments: dict[str, list[str]] = {}
    for assignment in organization.assignments:
        assignments.setdefault(assignment.company_slug, []).append(assignment.project_slug)
    for membership in organization.memberships:
        entry: PersonRoleEntry = {"company": membership.company_slug, "role": membership.role.value}
        if membership.role is not CompanyRole.ADMIN:
            entry["projects"] = assignments.get(membership.company_slug, [])
        roles.append(entry)
    return roles


class CompanySelectionOutcome(StrEnum):
    """Outcome of validating a requested company selection."""

    ACCEPTED = "accepted"
    UNKNOWN_COMPANY = "unknown_company"
    NOT_MEMBER = "not_member"


@dataclass(frozen=True)
class CompanySelection:
    """The validated outcome of a requested company selection."""

    outcome: CompanySelectionOutcome
    company: str | None
    eligible: tuple[str, ...] = ()


class CompanySelectionRefused(Exception):
    """A requested company selection failed existence or membership validation."""

    def __init__(self, outcome: CompanySelectionOutcome, company: str, eligible: tuple[str, ...] = ()) -> None:
        self.outcome = outcome
        self.company = company
        self.eligible = eligible
        super().__init__(f"{outcome.value}: {company}")


def resolve_company_selection(company: str, human_email: str | None) -> CompanySelection:
    """Validate a requested company against existence and, for a human requester, membership.

    A requester with no human email — the system principal's own path — is
    validated for existence alone, because it has no membership to consult.
    Every requester carrying a non-empty human email is authorized only by
    identity's membership answer; an email that resolves to no person has no
    memberships and is refused as not_member rather than downgraded to the
    existence-only path.
    """
    if find_company_config_path(company) is None:
        return CompanySelection(outcome=CompanySelectionOutcome.UNKNOWN_COMPANY, company=None)
    if not human_email:
        return CompanySelection(outcome=CompanySelectionOutcome.ACCEPTED, company=company)
    from teleclaude.core.identity import get_identity_resolver  # noqa: PLC0415 - deferred command-local dependency.

    identity = get_identity_resolver().resolve_by_email(human_email)
    if identity.person_slug is None:
        return CompanySelection(outcome=CompanySelectionOutcome.NOT_MEMBER, company=None)
    eligible = tuple(membership.company_slug for membership in resolve_organization(identity.person_slug).memberships)
    if company in eligible:
        return CompanySelection(outcome=CompanySelectionOutcome.ACCEPTED, company=company)
    return CompanySelection(outcome=CompanySelectionOutcome.NOT_MEMBER, company=None, eligible=eligible)


class SessionCompanyState(StrEnum):
    """Whether a session's operating company is settled."""

    RESOLVED = "resolved"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SessionCompanyContext:
    """The company a session operates the business of, resolved from its record.

    ``origin`` is the session's resolved principal (``human:<email>`` or
    ``system:daemon``), so a caller reads the operating scope and the acting
    identity from the one field without re-resolving either.
    """

    company: str | None
    origin: str
    state: SessionCompanyState
    eligible: tuple[str, ...] = ()


def resolve_session_company_context(session: Session) -> SessionCompanyContext:
    """Resolve the company context tools read for a session, from its record alone.

    The session record's own company wins. Otherwise a human-lineage person
    with exactly one eligible company resolves to it; several or none leaves
    the state unresolved, naming the eligible choices. Nobody re-derives or
    re-validates this answer — it is the single decision point.
    """
    principal, _role = resolve_session_principal(session)
    if session.company:
        return SessionCompanyContext(company=session.company, origin=principal, state=SessionCompanyState.RESOLVED)
    eligible: tuple[str, ...] = ()
    if session.human_email:
        from teleclaude.core.identity import get_identity_resolver  # noqa: PLC0415 - deferred command-local dependency.

        identity = get_identity_resolver().resolve_by_email(session.human_email)
        if identity.person_slug is not None:
            eligible = tuple(
                membership.company_slug for membership in resolve_organization(identity.person_slug).memberships
            )
    if len(eligible) == 1:
        return SessionCompanyContext(company=eligible[0], origin=principal, state=SessionCompanyState.RESOLVED)
    if len(eligible) > 1:
        return SessionCompanyContext(
            company=None, origin=principal, state=SessionCompanyState.AMBIGUOUS, eligible=eligible
        )
    return SessionCompanyContext(company=None, origin=principal, state=SessionCompanyState.ABSENT)
