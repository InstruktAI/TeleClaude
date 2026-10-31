"""Identity-owned target clearance for configuration commands.

The verb band (`require_cli_clearance`) answers "may this role call this
command"; it cannot see which instance, kind or fields a call touches. This
module answers that second question: given the caller's resolved standing and
the target of one configuration operation, decide whether it is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import (
    CliCaller,
    CliCallerKind,
    Company,
    PersonCliCaller,
    Project,
    RoleResolver,
    person_entries_for_email,
)
from teleclaude.cli.session_auth import ResolvedCliIdentity
from teleclaude.config.loader import company_memberships
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.constants import HUMAN_ROLE_MEMBER, SYSTEM_OPERATOR_PRINCIPAL

logger = get_logger(__name__)

_CONFIG_CLEARANCE_EVENT = "config_clearance"
_ORGANIZATION_SECTION = "organization"
_SINGLETON_KINDS = frozenset({ConfigSubjectKind.COMPUTER, ConfigSubjectKind.GLOBAL})

# PrincipalKind is the identity-owned CliCallerKind vocabulary (person/system/none):
# a configuration caller's standing is always resolved from the same carried principal
# every other local CLI surface resolves, so it carries the same three-way kind rather
# than a second, parallel enum for the same distinction.
PrincipalKind = CliCallerKind


class ConfigurationOperation(StrEnum):
    """The closed vocabulary of configuration verbs clearance decides over."""

    LIST = "list"
    GET = "get"
    INIT = "init"
    CREATE = "create"
    ADOPT = "adopt"
    PATCH = "patch"
    REMOVE = "remove"
    INVITE = "invite"
    BIND_VOICE_BOT = "bind_voice_bot"
    HELP_DESK_LINKS = "help_desk_links"


class RequiredStanding(StrEnum):
    """The closed vocabulary of standing a decision can require."""

    NONE = "none"
    THE_PERSON = "the_person"
    PLATFORM_ADMINISTRATOR = "platform_administrator"
    EFFECTIVE_ADMINISTRATOR = "effective_administrator"
    EFFECTIVE_MEMBER = "effective_member"
    REGISTERED_PERSON = "registered_person"
    COMPANY_MEMBER = "company_member"
    FORBIDDEN = "forbidden"


class ClearanceReason(StrEnum):
    """Closed reason tokens carried on every clearance decision."""

    VERB_BAND_ONLY = "verb_band_only"
    OWN_SETTINGS = "own_settings"
    PLATFORM_ADMINISTRATOR_REQUIRED = "platform_administrator_required"
    READ_ONLY_PROJECTION = "read_only_projection"
    NO_PERSON_STANDING = "no_person_standing"
    EFFECTIVE_ADMINISTRATOR_REQUIRED = "effective_administrator_required"
    EFFECTIVE_MEMBER_REQUIRED = "effective_member_required"
    COMPANY_MEMBERSHIP_REQUIRED = "company_membership_required"
    CREATION_FORM_REQUIRED = "creation_form_required"


class ProjectCreationForm(StrEnum):
    """Where a created project lands, which decides the standing creating it needs."""

    OWN_HOME = "own_home"
    COMPANY = "company"
    PLATFORM_PATH = "platform_path"


_ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class ConfigurationStanding:
    """The resolved caller's standing for a configuration decision."""

    person_slug: str | None
    platform_role: str | None
    principal_kind: PrincipalKind
    role_resolver: RoleResolver


@dataclass(frozen=True)
class ConfigurationTarget:
    """One configuration operation's addressed subject and touched sections."""

    kind: ConfigSubjectKind
    instance: str | None
    operation: ConfigurationOperation
    sections: frozenset[str]
    # Only project creation sets this; the company form names its company in `instance`.
    creation_form: ProjectCreationForm | None = None


@dataclass(frozen=True)
class ClearanceDecision:
    """The committed outcome of one target clearance decision."""

    allowed: bool
    required_standing: RequiredStanding
    reason: str


def standing_for(identity: ResolvedCliIdentity) -> ConfigurationStanding:
    """Resolve one caller's target standing from the gate's carried identity."""
    return standing_for_caller(identity.caller, identity.principal)


def standing_for_caller(caller: CliCaller, principal: str | None) -> ConfigurationStanding:
    """Resolve a caller's target standing, for any entry that has resolved its caller.

    The computer's operator holds platform-administrator standing while naming
    no person. Uses the exact-one identity lookup: an email mapping to zero or
    several registered people carries no person standing, even though the
    ordinary CLI identity retains its caller identity for other commands.
    """
    if caller.kind is CliCallerKind.SYSTEM and principal == SYSTEM_OPERATOR_PRINCIPAL:
        return ConfigurationStanding(
            person_slug=None, platform_role=_ADMIN_ROLE, principal_kind=caller.kind, role_resolver=RoleResolver()
        )
    if caller.kind is not CliCallerKind.PERSON:
        return ConfigurationStanding(
            person_slug=None, platform_role=None, principal_kind=caller.kind, role_resolver=RoleResolver()
        )
    if caller.email is None:
        return ConfigurationStanding(
            person_slug=None, platform_role=None, principal_kind=CliCallerKind.PERSON, role_resolver=RoleResolver()
        )
    people = person_entries_for_email(caller.email)
    if len(people) != 1:
        return ConfigurationStanding(
            person_slug=None, platform_role=None, principal_kind=CliCallerKind.PERSON, role_resolver=RoleResolver()
        )
    person = people[0]
    return ConfigurationStanding(
        person_slug=person.slug,
        platform_role=person.role,
        principal_kind=CliCallerKind.PERSON,
        role_resolver=RoleResolver(),
    )


def is_administrator(standing: ConfigurationStanding) -> bool:
    return standing.platform_role == _ADMIN_ROLE


def _decide_person(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if _ORGANIZATION_SECTION in target.sections:
        return ClearanceDecision(False, RequiredStanding.FORBIDDEN, ClearanceReason.READ_ONLY_PROJECTION)

    if target.operation in (
        ConfigurationOperation.INIT,
        ConfigurationOperation.REMOVE,
        ConfigurationOperation.INVITE,
        ConfigurationOperation.BIND_VOICE_BOT,
        ConfigurationOperation.LIST,
    ):
        if is_administrator(standing):
            return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
        return _refuse_admin_required(standing)

    # GET or PATCH: a person reads and changes their own instance, whatever it holds.
    is_own_instance = standing.person_slug is not None and standing.person_slug == target.instance
    if is_own_instance:
        if is_administrator(standing):
            return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.OWN_SETTINGS)
        return ClearanceDecision(True, RequiredStanding.THE_PERSON, ClearanceReason.OWN_SETTINGS)

    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


def _decide_company(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.operation is ConfigurationOperation.INIT:
        return ClearanceDecision(True, RequiredStanding.NONE, ClearanceReason.VERB_BAND_ONLY)
    if target.operation is ConfigurationOperation.LIST:
        if is_administrator(standing):
            return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
        return _refuse_admin_required(standing)
    if _effective_role(standing, Company(target.instance or "")) == _ADMIN_ROLE:
        return ClearanceDecision(True, RequiredStanding.EFFECTIVE_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_effective_admin_required(standing)


def _effective_role(standing: ConfigurationStanding, target: Company | Project) -> str:
    if standing.person_slug is None:
        return _ADMIN_ROLE if is_administrator(standing) else "customer"
    caller = PersonCliCaller(person_slug=standing.person_slug, human_role=standing.platform_role)
    return standing.role_resolver.role_for(caller, target)


def _refuse_effective_admin_required(standing: ConfigurationStanding) -> ClearanceDecision:
    if standing.principal_kind is not CliCallerKind.PERSON or standing.person_slug is None:
        return ClearanceDecision(
            False,
            RequiredStanding.EFFECTIVE_ADMINISTRATOR,
            ClearanceReason.NO_PERSON_STANDING,
        )
    return ClearanceDecision(
        False,
        RequiredStanding.EFFECTIVE_ADMINISTRATOR,
        ClearanceReason.EFFECTIVE_ADMINISTRATOR_REQUIRED,
    )


def _refuse_effective_member_required(standing: ConfigurationStanding) -> ClearanceDecision:
    if standing.principal_kind is not CliCallerKind.PERSON or standing.person_slug is None:
        return ClearanceDecision(False, RequiredStanding.EFFECTIVE_MEMBER, ClearanceReason.NO_PERSON_STANDING)
    return ClearanceDecision(False, RequiredStanding.EFFECTIVE_MEMBER, ClearanceReason.EFFECTIVE_MEMBER_REQUIRED)


def _refuse_no_person(required: RequiredStanding) -> ClearanceDecision:
    return ClearanceDecision(False, required, ClearanceReason.NO_PERSON_STANDING)


def _decide_adopt(standing: ConfigurationStanding, _target: ConfigurationTarget) -> ClearanceDecision:
    """Any registered person may adopt a folder, wherever it is."""
    if standing.person_slug is None:
        return _refuse_no_person(RequiredStanding.REGISTERED_PERSON)
    return ClearanceDecision(True, RequiredStanding.REGISTERED_PERSON, ClearanceReason.VERB_BAND_ONLY)


def _decide_create_in_own_home(standing: ConfigurationStanding, _target: ConfigurationTarget) -> ClearanceDecision:
    if standing.person_slug is None:
        return _refuse_no_person(RequiredStanding.THE_PERSON)
    return ClearanceDecision(True, RequiredStanding.THE_PERSON, ClearanceReason.VERB_BAND_ONLY)


def _decide_create_in_company(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    """A member of the company, any role, may create there; the platform role stands in for nothing."""
    if standing.person_slug is None:
        return _refuse_no_person(RequiredStanding.COMPANY_MEMBER)
    if target.instance is not None and target.instance in company_memberships(standing.person_slug):
        return ClearanceDecision(True, RequiredStanding.COMPANY_MEMBER, ClearanceReason.VERB_BAND_ONLY)
    return ClearanceDecision(False, RequiredStanding.COMPANY_MEMBER, ClearanceReason.COMPANY_MEMBERSHIP_REQUIRED)


def _decide_create_at_path(standing: ConfigurationStanding, _target: ConfigurationTarget) -> ClearanceDecision:
    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


_DECIDE_CREATE_BY_FORM = {
    ProjectCreationForm.OWN_HOME: _decide_create_in_own_home,
    ProjectCreationForm.COMPANY: _decide_create_in_company,
    ProjectCreationForm.PLATFORM_PATH: _decide_create_at_path,
}


def _decide_create(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.creation_form is None:
        return ClearanceDecision(False, RequiredStanding.FORBIDDEN, ClearanceReason.CREATION_FORM_REQUIRED)
    return _DECIDE_CREATE_BY_FORM[target.creation_form](standing, target)


def _decide_project(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.operation is ConfigurationOperation.ADOPT:
        return _decide_adopt(standing, target)
    if target.operation is ConfigurationOperation.CREATE:
        return _decide_create(standing, target)
    if target.operation in (ConfigurationOperation.LIST, ConfigurationOperation.GET):
        return ClearanceDecision(True, RequiredStanding.NONE, ClearanceReason.VERB_BAND_ONLY)
    project_role = _effective_role(standing, Project(target.instance or ""))
    if target.operation is ConfigurationOperation.PATCH:
        if project_role in (_ADMIN_ROLE, HUMAN_ROLE_MEMBER):
            return ClearanceDecision(True, RequiredStanding.EFFECTIVE_MEMBER, ClearanceReason.VERB_BAND_ONLY)
        return _refuse_effective_member_required(standing)
    if project_role == _ADMIN_ROLE:
        return ClearanceDecision(True, RequiredStanding.EFFECTIVE_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_effective_admin_required(standing)


def _decide_singleton(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.operation in (ConfigurationOperation.LIST, ConfigurationOperation.GET):
        return ClearanceDecision(True, RequiredStanding.NONE, ClearanceReason.VERB_BAND_ONLY)
    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


def _refuse_admin_required(standing: ConfigurationStanding) -> ClearanceDecision:
    if standing.principal_kind is not CliCallerKind.PERSON or standing.person_slug is None:
        return ClearanceDecision(False, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.NO_PERSON_STANDING)
    return ClearanceDecision(
        False, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.PLATFORM_ADMINISTRATOR_REQUIRED
    )


_DECIDE_BY_KIND = {
    ConfigSubjectKind.PERSON: _decide_person,
    ConfigSubjectKind.COMPANY: _decide_company,
    ConfigSubjectKind.PROJECT: _decide_project,
}


def decide(
    standing: ConfigurationStanding,
    target: ConfigurationTarget,
    *,
    request_id: str | None = None,
) -> ClearanceDecision:
    """Decide whether `standing` may perform `target`'s operation, and observe the decision."""
    if target.kind in _SINGLETON_KINDS:
        decision = _decide_singleton(standing, target)
    else:
        decision = _DECIDE_BY_KIND[target.kind](standing, target)
    logger.info(
        _CONFIG_CLEARANCE_EVENT,
        request_id=request_id,
        kind=target.kind.value,
        instance=target.instance,
        operation=target.operation.value,
        sections=sorted(target.sections),
        creation_form=target.creation_form.value if target.creation_form is not None else None,
        outcome="allowed" if decision.allowed else "refused",
        reason=decision.reason,
        required_standing=decision.required_standing.value,
        caller_person=standing.person_slug,
    )
    return decision
