"""Resolve and apply the identity-owned rule for records a principal may see."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import (
    CliCaller,
    PersonCliCaller,
    SystemCliCaller,
    human_principal_for_email,
    visitor_principal,
)
from teleclaude.config.declaration_changes import (
    subscribe_declaration_changes,
    unsubscribe_declaration_changes,
)
from teleclaude.config.identity_schema import CompanyRole
from teleclaude.config.loader import company_memberships, load_global_config
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.constants import HUMAN_ROLE_ADMIN, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.organization import resolve_organization
from teleclaude.project_manifest import ConfigKind
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.services.project_catalog.ownership import load_project_ownership_index

logger = get_logger(__name__)

_REACH_RESOLUTION_FAILED = "Identity reach resolution failed"
_PROJECT_TOKEN_PREFIX = "project:"
_PROJECT_TOKEN_LIKE_SUFFIX = "%"
_SQL_PARAM_PREFIX = "reach_"
_SQL_BIND_PLACEHOLDER_PREFIX = ":"
_SQL_PARAM_SEPARATOR = ", "
_SQL_OR_SEPARATOR = " OR "
_SQL_GROUP_TEMPLATE = "({clauses})"
_SQL_PARAMETER_TEMPLATE = "{name}_{index}"
_SQL_ASSIGNMENT_SUBJECT_PARAMETER = "assignment_subject_{index}"
_SQL_ASSIGNMENT_OWNER_PARAMETER = "assignment_owner_{index}"
_SQL_PERSON_OWNER_PARAMETER = "person_owner"
_SQL_SUBJECT_PARAMETER_GROUP = "subject"
_SQL_PRINCIPAL_PARAMETER_GROUP = "principal"
_SQL_PROJECT_PREFIX_PARAMETER = "project_prefix"
_SQL_REGISTERED_PROJECT_PARAMETER_GROUP = "registered_project"
_SQL_COMPANY_OWNER_PARAMETER_GROUP = "company_owner"
_SQL_COL_EQUAL_PARAMETER_TEMPLATE = "{column} = :{parameter}"
_SQL_NOT_IN_TEMPLATE = "{column} NOT IN ({values})"
_SQL_SUBJECT_MATCH_TEMPLATE = "{subject_col} IN ({tokens})"
_SQL_PRINCIPAL_MATCH_TEMPLATE = "{principal_col} = :{parameter}"
_SQL_OWNER_MATCH_TEMPLATE = "({subject_col} LIKE :{prefix_parameter} AND {registered_clause} AND ({owner_clause}))"
_SQL_ASSIGNMENT_MATCH_TEMPLATE = "({subject_col} = :{subject_parameter} AND {owner_col} = :{owner_parameter})"
_SQL_OWNER_IN_TEMPLATE = "{owner_col} IN ({tokens})"
_SQL_FALSE = "1 = 0"
_SQL_TRUE = "1 = 1"


class ReachResolutionError(RuntimeError):
    """A non-declaration failure prevented reliable reach resolution."""


@dataclass(frozen=True)
class Reach:
    """One principal's visibility facts and their shared record/query appliers."""

    everything: bool
    subjects: frozenset[str]
    registered_projects: frozenset[str]
    administered_companies: frozenset[str]
    assignments: frozenset[tuple[str, str]]
    person_slug: str | None
    shared_documentation: bool
    principal: str | None
    email: str | None = None

    def admits(self, subject: str | None, owner: str | None, principal: str | None) -> bool:
        """Return whether a record's recorded facts fall within this reach."""
        if self.everything:
            return True
        if principal is not None and principal == self.principal:
            return True
        if subject is None:
            return False
        if subject in self.subjects:
            return True
        try:
            subject_ref = SubjectRef.from_token(subject)
        except ValueError:
            return False
        if subject_ref.kind is not ConfigSubjectKind.PROJECT or subject_ref.instance is None:
            return False
        project_slug = subject_ref.instance
        if project_slug in self.registered_projects or owner is None:
            return False
        try:
            owner_ref = SubjectRef.from_token(owner)
        except ValueError:
            return False
        if owner_ref.kind is ConfigSubjectKind.COMPANY and owner_ref.instance is not None:
            return (
                owner_ref.instance in self.administered_companies
                or (
                    owner_ref.instance,
                    project_slug,
                )
                in self.assignments
            )
        return (
            owner_ref.kind is ConfigSubjectKind.PERSON
            and owner_ref.instance is not None
            and owner_ref.instance == self.person_slug
        )

    def sql_predicate(
        self,
        *,
        subject_col: str,
        owner_col: str,
        principal_col: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Return a bound SQL predicate equivalent to :meth:`admits`."""
        if self.everything:
            return _SQL_TRUE, {}

        clauses: list[str] = []
        parameters: dict[str, str] = {}
        subject_tokens = sorted(self.subjects)
        if subject_tokens:
            placeholders = _bind_values(parameters, subject_tokens, _SQL_SUBJECT_PARAMETER_GROUP)
            clauses.append(_SQL_SUBJECT_MATCH_TEMPLATE.format(subject_col=subject_col, tokens=placeholders))

        if principal_col is not None and self.principal is not None:
            parameter = _SQL_PARAM_PREFIX + _SQL_PRINCIPAL_PARAMETER_GROUP
            parameters[parameter] = self.principal
            clauses.append(_SQL_PRINCIPAL_MATCH_TEMPLATE.format(principal_col=principal_col, parameter=parameter))

        owner_clause = _owner_clause(self, subject_col, owner_col, parameters)
        if owner_clause:
            prefix_parameter = _SQL_PARAM_PREFIX + _SQL_PROJECT_PREFIX_PARAMETER
            parameters[prefix_parameter] = _PROJECT_TOKEN_PREFIX + _PROJECT_TOKEN_LIKE_SUFFIX
            registered = _bind_values(
                parameters,
                [SubjectRef(ConfigSubjectKind.PROJECT, slug).to_token() for slug in sorted(self.registered_projects)],
                _SQL_REGISTERED_PROJECT_PARAMETER_GROUP,
            )
            registered_clause = (
                _SQL_NOT_IN_TEMPLATE.format(column=subject_col, values=registered) if registered else _SQL_TRUE
            )
            clauses.append(
                _SQL_OWNER_MATCH_TEMPLATE.format(
                    subject_col=subject_col,
                    prefix_parameter=prefix_parameter,
                    registered_clause=registered_clause,
                    owner_clause=owner_clause,
                )
            )

        predicate = _SQL_GROUP_TEMPLATE.format(clauses=_SQL_OR_SEPARATOR.join(clauses)) if clauses else _SQL_FALSE
        return predicate, parameters


def _bind_values(parameters: dict[str, str], values: list[str], name: str) -> str:
    """Add named SQL values and return their placeholder list."""
    placeholders: list[str] = []
    for index, value in enumerate(values):
        parameter = _SQL_PARAMETER_TEMPLATE.format(name=_SQL_PARAM_PREFIX + name, index=index)
        parameters[parameter] = value
        placeholders.append(_SQL_BIND_PLACEHOLDER_PREFIX + parameter)
    return _SQL_PARAM_SEPARATOR.join(placeholders)


def _owner_clause(reach: Reach, subject_col: str, owner_col: str, parameters: dict[str, str]) -> str:
    """Build only the owner grants for unregistered project subjects."""
    # A receiver's local registry cannot grant access to a remote project it does not register.
    clauses: list[str] = []
    company_owners = sorted(
        SubjectRef(ConfigSubjectKind.COMPANY, slug).to_token() for slug in reach.administered_companies
    )
    if company_owners:
        placeholders = _bind_values(parameters, company_owners, _SQL_COMPANY_OWNER_PARAMETER_GROUP)
        clauses.append(_SQL_OWNER_IN_TEMPLATE.format(owner_col=owner_col, tokens=placeholders))
    for index, (company, project) in enumerate(sorted(reach.assignments)):
        subject_parameter = _SQL_PARAM_PREFIX + _SQL_ASSIGNMENT_SUBJECT_PARAMETER.format(index=index)
        owner_parameter = _SQL_PARAM_PREFIX + _SQL_ASSIGNMENT_OWNER_PARAMETER.format(index=index)
        parameters[subject_parameter] = SubjectRef(ConfigSubjectKind.PROJECT, project).to_token()
        parameters[owner_parameter] = SubjectRef(ConfigSubjectKind.COMPANY, company).to_token()
        clauses.append(
            _SQL_ASSIGNMENT_MATCH_TEMPLATE.format(
                subject_col=subject_col,
                subject_parameter=subject_parameter,
                owner_col=owner_col,
                owner_parameter=owner_parameter,
            )
        )
    if reach.person_slug is not None:
        person_parameter = _SQL_PARAM_PREFIX + _SQL_PERSON_OWNER_PARAMETER
        parameters[person_parameter] = SubjectRef(ConfigSubjectKind.PERSON, reach.person_slug).to_token()
        clauses.append(_SQL_COL_EQUAL_PARAMETER_TEMPLATE.format(column=owner_col, parameter=person_parameter))
    return _SQL_GROUP_TEMPLATE.format(clauses=_SQL_OR_SEPARATOR.join(clauses)) if clauses else ""


def resolve_reach(caller: CliCaller | None) -> Reach:
    """Resolve current membership and ownership facts for one request caller."""
    principal: str | None = None
    if isinstance(caller, SystemCliCaller):
        return Reach(True, frozenset(), frozenset(), frozenset(), frozenset(), None, True, SYSTEM_DAEMON_PRINCIPAL)
    if not isinstance(caller, PersonCliCaller) or caller.person_slug is None:
        return Reach(False, frozenset(), frozenset(), frozenset(), frozenset(), None, False, None)
    try:
        person = next((entry for entry in load_global_config().people if entry.slug == caller.person_slug), None)
        email = caller.email or (person.email if person is not None else None)
        if email is not None:
            principal = human_principal_for_email(email)
        if person is not None and person.role == HUMAN_ROLE_ADMIN:
            return Reach(
                everything=True,
                subjects=frozenset(),
                registered_projects=frozenset(),
                administered_companies=frozenset(),
                assignments=frozenset(),
                person_slug=caller.person_slug,
                shared_documentation=True,
                principal=principal,
                email=email,
            )

        organization = resolve_organization(caller.person_slug)
        memberships = company_memberships(caller.person_slug)
        administered_companies = frozenset(
            membership.company_slug for membership in organization.memberships if membership.role is CompanyRole.ADMIN
        )
        assignments = frozenset(
            {(assignment.company_slug, assignment.project_slug) for assignment in organization.assignments}
            | {(company, project) for company, member in memberships.items() for project in member.projects}
        )
        covered_projects = frozenset((covered.company_slug, covered.project_slug) for covered in organization.covered)
        ownership_index = load_project_ownership_index()
        ownerships = ownership_index.ownerships()
        registered_projects = {ownership.project_slug for ownership in ownerships}
        catalog = get_project_catalog_service()
        registered_projects.update(
            entry.identity
            for entry in catalog.list_entries()
            if entry.kind is ConfigKind.PROJECT and entry.identity is not None
        )

        reached_subjects = {SubjectRef(ConfigSubjectKind.PERSON, caller.person_slug).to_token()}
        reached_subjects.update(SubjectRef(ConfigSubjectKind.COMPANY, slug).to_token() for slug in memberships)
        for ownership in ownerships:
            if (
                ownership.person == caller.person_slug
                or (ownership.company, ownership.project_slug) in covered_projects
            ):
                reached_subjects.add(SubjectRef(ConfigSubjectKind.PROJECT, ownership.project_slug).to_token())
            elif ownership.company is not None and (ownership.company, ownership.project_slug) in assignments:
                reached_subjects.add(SubjectRef(ConfigSubjectKind.PROJECT, ownership.project_slug).to_token())

        return Reach(
            everything=False,
            subjects=frozenset(reached_subjects),
            registered_projects=frozenset(registered_projects),
            administered_companies=administered_companies,
            assignments=assignments,
            person_slug=caller.person_slug,
            shared_documentation=bool(administered_companies),
            principal=principal,
            email=email,
        )
    except ReachResolutionError:
        raise
    except Exception as exc:
        logger.exception(_REACH_RESOLUTION_FAILED)
        raise ReachResolutionError(_REACH_RESOLUTION_FAILED) from exc


def visitor_reach(identity_key: str) -> Reach:
    """The reach of an unregistered desk visitor: exactly the records kept under the platform identity they wrote from.

    Being about the desk's home admits nothing here; the people whose reach covers that
    home see the same records through their own reach.
    """
    return Reach(
        everything=False,
        subjects=frozenset(),
        registered_projects=frozenset(),
        administered_companies=frozenset(),
        assignments=frozenset(),
        person_slug=None,
        shared_documentation=False,
        principal=visitor_principal(identity_key),
    )


class ReachCache:
    """Resolve once for a live consumer and invalidate on declaration changes."""

    def __init__(self, caller: CliCaller, on_invalidate: Callable[[], None] | None = None) -> None:
        self._caller = caller
        self._reach: Reach | None = None
        self._on_invalidate = on_invalidate
        subscribe_declaration_changes(self.invalidate)

    def get(self) -> Reach:
        """Return the cached reach, resolving it on first use or after invalidation."""
        if self._reach is None:
            self._reach = resolve_reach(self._caller)
        return self._reach

    def invalidate(self) -> None:
        """Drop the resolved value after a config-owned declaration change."""
        had_reach = self._reach is not None
        self._reach = None
        if had_reach and self._on_invalidate is not None:
            self._on_invalidate()

    def close(self) -> None:
        """Stop receiving config change notifications when the consumer closes."""
        unsubscribe_declaration_changes(self.invalidate)
