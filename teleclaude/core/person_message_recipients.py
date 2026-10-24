"""Resolve person-message recipients from the caller's declared authority."""

from __future__ import annotations

from teleclaude.caller_identity import PersonCliCaller, SystemCliCaller, caller_from_principal
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.core.organization import platform_admin_roster

_NO_CALLER_PRINCIPAL = "The caller has no principal; name a recipient with --recipient <slug>."
_HUMAN_PRINCIPAL_UNRESOLVABLE = (
    "The caller's human principal {email} does not resolve to an addressable roster person; "
    "name a recipient with --recipient <slug>."
)
_NO_PLATFORM_ADMINS = (
    "The system principal has no platform admins on the people roster; name a recipient with --recipient <slug>."
)


class RecipientUnresolvableError(ValueError):
    """The caller's authority does not resolve to an addressable recipient."""


def resolve_person_message_recipients(
    recipient: str | None,
    principal: str | None,
) -> tuple[str | PersonEntry, ...]:
    """Resolve an explicit recipient or the addressable people under a principal."""
    if recipient is not None:
        return (recipient,)

    caller = caller_from_principal(principal)
    if isinstance(caller, PersonCliCaller):
        if caller.person_slug is not None:
            return (caller.person_slug,)
        raise RecipientUnresolvableError(_HUMAN_PRINCIPAL_UNRESOLVABLE.format(email=caller.email or principal))
    if isinstance(caller, SystemCliCaller):
        admins = tuple(platform_admin_roster())
        if admins:
            return admins
        raise RecipientUnresolvableError(_NO_PLATFORM_ADMINS)
    raise RecipientUnresolvableError(_NO_CALLER_PRINCIPAL)
