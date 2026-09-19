"""Company roster validation and mutation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import (
    find_person_entry,
    list_company_configs,
    load_global_config,
    save_company_config,
    save_global_config,
)
from teleclaude.config.schema import CompanyConfig, CompanyMember, CompanyRole, GlobalConfig
from teleclaude.services.project_catalog import get_project_catalog_service

logger = get_logger(__name__)

_ROSTER_WRITE_EVENT = "roster_write"
_REFUSAL_TEMPLATE = "{}: {}"
_DELTA_REFERENT = "delta"


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
class RosterDelta:
    """The complete roster changes requested for one person."""

    membership: tuple[str, CompanyRole] | None = None
    remove_company: str | None = None
    assign: tuple[str, ...] = ()
    unassign: tuple[str, ...] = ()


@dataclass(frozen=True)
class RosterOutcome:
    """The files written and assignments removed by one roster mutation."""

    companies_written: tuple[str, ...]
    removed_assignments: tuple[tuple[str, str], ...]


def _primary_kind(delta: RosterDelta) -> RosterWriteKind:
    """Choose the leading requested operation for the one mutation record."""
    if delta.membership is not None:
        return RosterWriteKind.MEMBERSHIP
    if delta.remove_company is not None:
        return RosterWriteKind.MEMBERSHIP_WITHDRAWN
    if delta.assign:
        return RosterWriteKind.ASSIGNMENT
    return RosterWriteKind.UNASSIGNMENT


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


def _clone_companies() -> dict[str, CompanyConfig]:
    """Load mutable copies of every company configuration keyed by company slug."""
    return {slug: config.model_copy(deep=True) for slug, config in list_company_configs()}


def _save_roster_changes(
    original_companies: dict[str, CompanyConfig],
    changed_companies: dict[str, CompanyConfig],
    global_config: GlobalConfig | None = None,
    original_global_config: GlobalConfig | None = None,
) -> None:
    """Persist a complete mutation or restore every already-written source on failure."""
    written_companies: list[str] = []
    try:
        for company_slug in sorted(changed_companies):
            save_company_config(company_slug, changed_companies[company_slug])
            written_companies.append(company_slug)
        if global_config is not None:
            save_global_config(global_config)
    except (OSError, ValueError):
        for company_slug in reversed(written_companies):
            save_company_config(company_slug, original_companies[company_slug])
        if original_global_config is not None:
            save_global_config(original_global_config)
        raise


def person_has_roster_membership(person_slug: str) -> bool:
    """Return whether any company roster currently names a person."""
    return any(person_slug in config.members for _, config in list_company_configs())


def _validate_delta(delta: RosterDelta) -> None:
    """Reject conflicting operations before any company configuration is changed."""
    if delta.membership is not None and delta.membership[0] == delta.remove_company:
        raise RosterRefused(RosterRefusal.CONTRADICTORY_DELTA, _DELTA_REFERENT)
    if set(delta.assign).intersection(delta.unassign):
        raise RosterRefused(RosterRefusal.CONTRADICTORY_DELTA, _DELTA_REFERENT)


def _membership_companies(companies: dict[str, CompanyConfig], person_slug: str) -> set[str]:
    """Return every company whose roster currently declares the person."""
    return {company_slug for company_slug, config in companies.items() if person_slug in config.members}


def _remove_assignments(
    companies: dict[str, CompanyConfig],
    changed_companies: set[str],
    person_slug: str,
    project_slugs: tuple[str, ...],
) -> list[tuple[str, str]]:
    """Remove matching assignments wherever the roster stores them."""
    removed: list[tuple[str, str]] = []
    requested = set(project_slugs)
    for company_slug, config in companies.items():
        member = config.members.get(person_slug)
        if member is None:
            continue
        remaining = [project_slug for project_slug in member.projects if project_slug not in requested]
        removed_projects = [project_slug for project_slug in member.projects if project_slug in requested]
        if removed_projects:
            member.projects = remaining
            changed_companies.add(company_slug)
            removed.extend((company_slug, project_slug) for project_slug in removed_projects)
    return removed


def apply_roster_delta(person_slug: str, delta: RosterDelta) -> RosterOutcome:
    """Validate and atomically persist one person's complete requested roster delta."""
    kind = _primary_kind(delta)
    try:
        _validate_delta(delta)
        if find_person_entry(people=load_global_config().people, person_slug=person_slug) is None:
            raise RosterRefused(RosterRefusal.UNKNOWN_PERSON, person_slug)

        original_companies = _clone_companies()
        companies = {slug: config.model_copy(deep=True) for slug, config in original_companies.items()}
        changed_companies: set[str] = set()
        removed_assignments: list[tuple[str, str]] = []

        if delta.membership is not None:
            membership_company, membership_role = delta.membership
            config = companies.get(membership_company)
            if config is None:
                raise RosterRefused(RosterRefusal.UNKNOWN_COMPANY, membership_company)
            member = config.members.get(person_slug)
            member_projects = list(member.projects) if member is not None else []
            config.members[person_slug] = CompanyMember(role=membership_role, projects=member_projects)
            changed_companies.add(membership_company)

        if delta.remove_company is not None:
            config = companies.get(delta.remove_company)
            if config is None:
                raise RosterRefused(RosterRefusal.UNKNOWN_COMPANY, delta.remove_company)
            removed_member = config.members.pop(person_slug, None)
            if removed_member is not None:
                changed_companies.add(delta.remove_company)
                removed_assignments.extend(
                    (delta.remove_company, project_slug) for project_slug in removed_member.projects
                )

        memberships = _membership_companies(companies, person_slug)
        projects_by_slug = {project.slug: project for project in get_project_catalog_service().list_projects()}
        for project_slug in delta.assign:
            project = projects_by_slug.get(project_slug)
            if project is None:
                raise RosterRefused(RosterRefusal.UNKNOWN_PROJECT, project_slug)
            company_slug = project.config.company
            if company_slug is None:
                raise RosterRefused(RosterRefusal.PROJECT_NOT_OWNED_BY_COMPANY, project_slug)
            if company_slug not in companies:
                raise RosterRefused(RosterRefusal.PROJECT_NOT_OWNED_BY_COMPANY, project_slug)
            if company_slug not in memberships:
                raise RosterRefused(RosterRefusal.NOT_A_MEMBER, company_slug)
            member = companies[company_slug].members[person_slug]
            if project_slug not in member.projects:
                member.projects.append(project_slug)
                changed_companies.add(company_slug)

        removed_assignments.extend(_remove_assignments(companies, changed_companies, person_slug, delta.unassign))
        outcome = RosterOutcome(
            companies_written=tuple(sorted(changed_companies)),
            removed_assignments=tuple(removed_assignments),
        )
        _save_roster_changes(
            original_companies,
            {company_slug: companies[company_slug] for company_slug in outcome.companies_written},
        )
    except RosterRefused as error:
        _observe_write(
            outcome=RosterWriteOutcome.REFUSED,
            kind=kind,
            person_slug=person_slug,
            companies_written=(),
            removed_assignments=(),
            reason=error.reason,
        )
        raise
    _observe_write(
        outcome=RosterWriteOutcome.ACCEPTED,
        kind=kind,
        person_slug=person_slug,
        companies_written=outcome.companies_written,
        removed_assignments=outcome.removed_assignments,
    )
    return outcome


def remove_person_from_rosters(
    person_slug: str,
    global_config: GlobalConfig | None = None,
    original_global_config: GlobalConfig | None = None,
) -> RosterOutcome:
    """Remove one person's membership entry from every company roster."""
    original_companies = _clone_companies()
    companies = {slug: config.model_copy(deep=True) for slug, config in original_companies.items()}
    changed_companies: set[str] = set()
    removed_assignments: list[tuple[str, str]] = []
    for company_slug, config in companies.items():
        member = config.members.pop(person_slug, None)
        if member is not None:
            changed_companies.add(company_slug)
            removed_assignments.extend((company_slug, project_slug) for project_slug in member.projects)
    outcome = RosterOutcome(
        companies_written=tuple(sorted(changed_companies)),
        removed_assignments=tuple(removed_assignments),
    )
    _save_roster_changes(
        original_companies,
        {company_slug: companies[company_slug] for company_slug in outcome.companies_written},
        global_config,
        original_global_config,
    )
    _observe_write(
        outcome=RosterWriteOutcome.ACCEPTED,
        kind=RosterWriteKind.PERSON_REMOVED,
        person_slug=person_slug,
        companies_written=outcome.companies_written,
        removed_assignments=outcome.removed_assignments,
    )
    return outcome
