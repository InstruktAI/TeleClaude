"""Company roster validation and mutation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config
from teleclaude.config.schema import CompanyConfig
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

_ROSTER_WRITE_EVENT = "roster_write"
_REFUSAL_TEMPLATE = "{}: {}"


class RosterRefusal(StrEnum):
    """Closed reasons a roster delta cannot be applied."""

    UNKNOWN_PERSON = "unknown_person"
    UNKNOWN_COMPANY = "unknown_company"
    UNKNOWN_PROJECT = "unknown_project"
    PROJECT_NOT_OWNED_BY_COMPANY = "project_not_owned_by_company"
    NOT_A_MEMBER = "not_a_member"
    CONTRADICTORY_DELTA = "contradictory_delta"


class RosterWriteKind(StrEnum):
    """The primary roster operation represented in an observation."""

    MEMBERSHIP = "membership"
    MEMBERSHIP_WITHDRAWN = "membership_withdrawn"
    ASSIGNMENT = "assignment"
    UNASSIGNMENT = "unassignment"
    PERSON_REMOVED = "person_removed"


class RosterWriteOutcome(StrEnum):
    """Terminal outcomes for a roster mutation attempt."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


class RosterRefused(ValueError):
    """A typed roster rejection carrying its reason and referent."""

    def __init__(self, reason: RosterRefusal, referent: str) -> None:
        self.reason = reason
        self.referent = referent
        super().__init__(_REFUSAL_TEMPLATE.format(reason.value, referent))


@dataclass(frozen=True)
class RosterOutcome:
    """The files written and assignments removed by one roster mutation."""

    companies_written: tuple[str, ...]
    removed_assignments: tuple[tuple[str, str], ...]


def _observe_write(
    *,
    outcome: RosterWriteOutcome,
    kind: RosterWriteKind,
    person_slug: str,
    companies_written: tuple[str, ...],
    removed_assignments: tuple[tuple[str, str], ...],
    reason: RosterRefusal | None = None,
) -> None:
    """Emit one structured outcome for one complete roster mutation attempt."""
    logger.info(
        _ROSTER_WRITE_EVENT,
        outcome=outcome.value,
        kind=kind.value,
        reason=reason.value if reason is not None else None,
        person=person_slug,
        companies_written=companies_written,
        removed_assignments=removed_assignments,
    )


def validate_roster_candidate(company_slug: str, committed: CompanyConfig, candidate: CompanyConfig) -> None:
    """Validate only the members and assignments a `candidate` newly introduces.

    Compares against `committed` member-by-member: an unchanged member (same
    role, same projects) is never re-validated, so a stale assignment made
    invalid elsewhere never blocks an unrelated edit to this roster (inert,
    not fatal). For every added or changed member: the person must be
    registered, and every project newly present in that member's list (not
    already assigned to them in `committed`) must be registered and owned by
    this company. Raises `RosterRefused` and writes nothing on failure; emits
    one `roster_write` observation per changed or withdrawn member on success.
    """
    people = {person.slug for person in load_global_config().people if person.slug}
    projects_by_slug = {project.slug: project for project in get_project_catalog_service().list_projects()}

    for person_slug, member in candidate.members.items():
        committed_member = committed.members.get(person_slug)
        if (
            committed_member is not None
            and committed_member.role == member.role
            and committed_member.projects == member.projects
        ):
            continue
        if person_slug not in people:
            raise RosterRefused(RosterRefusal.UNKNOWN_PERSON, person_slug)
        previously_assigned = set(committed_member.projects) if committed_member is not None else set()
        for project_slug in member.projects:
            if project_slug in previously_assigned:
                continue
            project = projects_by_slug.get(project_slug)
            if project is None:
                raise RosterRefused(RosterRefusal.UNKNOWN_PROJECT, project_slug)
            if project.config.company != company_slug:
                raise RosterRefused(RosterRefusal.PROJECT_NOT_OWNED_BY_COMPANY, project_slug)

    for person_slug, member in candidate.members.items():
        committed_member = committed.members.get(person_slug)
        if (
            committed_member is None
            or committed_member.role != member.role
            or committed_member.projects != member.projects
        ):
            _observe_write(
                outcome=RosterWriteOutcome.ACCEPTED,
                kind=RosterWriteKind.MEMBERSHIP,
                person_slug=person_slug,
                companies_written=(company_slug,),
                removed_assignments=(),
            )
    for person_slug, member in committed.members.items():
        if person_slug not in candidate.members:
            _observe_write(
                outcome=RosterWriteOutcome.ACCEPTED,
                kind=RosterWriteKind.MEMBERSHIP_WITHDRAWN,
                person_slug=person_slug,
                companies_written=(company_slug,),
                removed_assignments=tuple((company_slug, project_slug) for project_slug in member.projects),
            )


def rosters_without_person(
    companies: Mapping[str, CompanyConfig],
    slug: str,
) -> tuple[dict[str, CompanyConfig], RosterOutcome]:
    """Return the changed companies and outcome of removing `slug` from every roster.

    Pure: no load, no save. Callers persist the returned companies under locks
    they already hold and observe the outcome themselves after committing.
    """
    changed_companies: dict[str, CompanyConfig] = {}
    removed_assignments: list[tuple[str, str]] = []
    for company_slug, config in companies.items():
        if slug not in config.members:
            continue
        candidate = config.model_copy(deep=True)
        member = candidate.members.pop(slug)
        changed_companies[company_slug] = candidate
        removed_assignments.extend((company_slug, project_slug) for project_slug in member.projects)
    outcome = RosterOutcome(
        companies_written=tuple(sorted(changed_companies)),
        removed_assignments=tuple(removed_assignments),
    )
    return changed_companies, outcome
