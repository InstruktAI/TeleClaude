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

from teleclaude.config.resource_contract import ConfigSubjectKind
from teleclaude.core.identity import CliCallerKind, caller_from_principal, get_identity_resolver

logger = get_logger(__name__)

_CONFIG_CLEARANCE_EVENT = "config_clearance"
_ORGANIZATION_SECTION = "organization"
_IDENTITY_SECTION = "identity"
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
    PATCH = "patch"
    REMOVE = "remove"
    INVITE = "invite"
    BIND_VOICE_BOT = "bind_voice_bot"


class RequiredStanding(StrEnum):
    """The closed vocabulary of standing a decision can require."""

    NONE = "none"
    THE_PERSON = "the_person"
    PLATFORM_ADMINISTRATOR = "platform_administrator"
    FORBIDDEN = "forbidden"


class ClearanceReason(StrEnum):
    """Closed reason tokens carried on every clearance decision."""

    VERB_BAND_ONLY = "verb_band_only"
    OWN_SETTINGS = "own_settings"
    PLATFORM_ADMINISTRATOR_REQUIRED = "platform_administrator_required"
    READ_ONLY_PROJECTION = "read_only_projection"
    NO_PERSON_STANDING = "no_person_standing"


_ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class ConfigurationStanding:
    """The resolved caller's standing for a configuration decision."""

    person_slug: str | None
    platform_role: str | None
    principal_kind: PrincipalKind


@dataclass(frozen=True)
class ConfigurationTarget:
    """One configuration operation's addressed subject and touched sections."""

    kind: ConfigSubjectKind
    instance: str | None
    operation: ConfigurationOperation
    sections: frozenset[str]


@dataclass(frozen=True)
class ClearanceDecision:
    """The committed outcome of one target clearance decision."""

    allowed: bool
    required_standing: RequiredStanding
    reason: str


def standing_for(principal: str | None) -> ConfigurationStanding:
    """Resolve one caller's configuration standing from their carried principal.

    Uses the exact-one identity lookup: an email mapping to zero or several
    registered people carries no person standing, distinct from `caller_from_principal`'s
    ordinary (non-exact) resolution used elsewhere in the CLI.
    """
    caller = caller_from_principal(principal)
    if caller.kind is not CliCallerKind.PERSON:
        return ConfigurationStanding(person_slug=None, platform_role=None, principal_kind=caller.kind)
    if caller.email is None:
        return ConfigurationStanding(person_slug=None, platform_role=None, principal_kind=CliCallerKind.PERSON)
    context = get_identity_resolver().resolve_exact_one_by_email(caller.email)
    return ConfigurationStanding(
        person_slug=context.person_slug,
        platform_role=context.person_role,
        principal_kind=CliCallerKind.PERSON,
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

    # GET or PATCH: self-service is possible only on the caller's own instance, and only
    # when a patch names no `identity` field — identity changes are never self-service.
    is_own_instance = standing.person_slug is not None and standing.person_slug == target.instance
    patches_identity = target.operation is ConfigurationOperation.PATCH and _IDENTITY_SECTION in target.sections
    if is_own_instance and not patches_identity:
        if is_administrator(standing):
            return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.OWN_SETTINGS)
        return ClearanceDecision(True, RequiredStanding.THE_PERSON, ClearanceReason.OWN_SETTINGS)

    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


def _decide_company(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.operation is ConfigurationOperation.INIT:
        return ClearanceDecision(True, RequiredStanding.NONE, ClearanceReason.VERB_BAND_ONLY)
    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


def _decide_project(standing: ConfigurationStanding, target: ConfigurationTarget) -> ClearanceDecision:
    if target.operation in (ConfigurationOperation.LIST, ConfigurationOperation.GET, ConfigurationOperation.INIT):
        return ClearanceDecision(True, RequiredStanding.NONE, ClearanceReason.VERB_BAND_ONLY)
    if is_administrator(standing):
        return ClearanceDecision(True, RequiredStanding.PLATFORM_ADMINISTRATOR, ClearanceReason.VERB_BAND_ONLY)
    return _refuse_admin_required(standing)


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
        outcome="allowed" if decision.allowed else "refused",
        reason=decision.reason,
        required_standing=decision.required_standing.value,
        caller_person=standing.person_slug,
    )
    return decision
