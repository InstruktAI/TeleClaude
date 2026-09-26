"""Resolution of declared company memberships and project assignments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import find_company_config_path, list_company_configs
from teleclaude.config.schema import CompanyRole
from teleclaude.core.db._sync import resolve_session_principal
from teleclaude.core.identity import get_identity_resolver
from teleclaude.services.project_catalog import get_project_catalog_service

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_ORGANIZATION_RESOLVED_EVENT = "organization_resolved"
_ORGANIZATION_STALE_ASSIGNMENT_EVENT = "organization_stale_assignment"


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


def resolve_organization(person_slug: str) -> OrganizationalMembership:
    """Resolve a person's declared company roles and current project relationships."""
    projects = {project.slug: project for project in get_project_catalog_service().list_projects()}
    memberships: list[CompanyMembership] = []
    assignments: list[ProjectRef] = []
    covered: list[ProjectRef] = []
    stale: list[StaleAssignment] = []
    for company_slug, company in list_company_configs():
        member = company.members.get(person_slug)
        if member is None:
            continue
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
