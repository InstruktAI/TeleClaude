"""Resolution of declared company memberships and project assignments."""

from __future__ import annotations

from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import list_company_configs
from teleclaude.config.schema import CompanyRole
from teleclaude.services.project_catalog import get_project_catalog_service

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
