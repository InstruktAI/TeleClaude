"""Daemon intake for client-carried identity and caller provenance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException
from starlette.requests import HTTPConnection

from teleclaude.caller_identity import (
    CarriedIdentity,
    CliCaller,
    NoIdentityCliCaller,
    Person,
    PersonCliCaller,
    Platform,
    RoleResolver,
    SessionOf,
    SystemCliCaller,
    caller_from_principal,
    human_principal_for_email,
    is_roleless_platform_caller,
)
from teleclaude.cli.telec.auth import is_command_allowed_for
from teleclaude.config.machine import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, LOGIN_REQUIRED_DETAIL, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.conversation_messages import resolve_session_event_author
from teleclaude.core.daemon_lifecycle_identity import is_daemon_credential
from teleclaude.core.db import db
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.roles import resolve_session_role
from teleclaude.types.commands import CallerProvenance
from teleclaude.types.creation_record import EntryPoint

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_CLEARANCE_REFUSAL = "permission denied — role is not permitted to call {command_path}"
_DAEMON_TOKEN_HEADER = "x-teleclaude-daemon-token"


@dataclass(frozen=True)
class CallerIdentity:
    """Identity the request's client resolved and carried to the daemon."""

    session_id: str
    role: str | None
    human_role: str | None
    email: str | None = None
    principal: str | None = None
    entry_point: EntryPoint | None = None
    company: str | None = None
    command: str | None = None


def caller_role_for_session(identity: CallerIdentity, session: Session) -> str | None:
    """Resolve a carried caller's effective role for a session's project."""
    caller = caller_for_role_resolution(identity)
    if isinstance(caller, PersonCliCaller):
        if not caller.person_slug:
            return "customer"
        return RoleResolver().role_for(caller, SessionOf(session.project_path))
    if isinstance(caller, SystemCliCaller):
        return identity.role
    if identity.email is not None:
        return "customer"
    return None


def caller_role_at_platform(identity: CallerIdentity) -> str | None:
    """Resolve a carried caller's role for a platform-wide target."""
    caller = caller_for_role_resolution(identity)
    if isinstance(caller, PersonCliCaller):
        return RoleResolver().role_for(caller, Platform())
    if isinstance(caller, SystemCliCaller):
        return identity.role
    if identity.email is not None:
        return "customer"
    return None


def caller_role_at_own_person_scope(identity: CallerIdentity) -> str | None:
    """Resolve a carried caller's role at their own person scope, the scope that admits any registered person."""
    caller = caller_for_role_resolution(identity)
    if isinstance(caller, PersonCliCaller):
        if not caller.person_slug:
            return HUMAN_ROLE_CUSTOMER
        return RoleResolver().role_for(caller, Person(caller.person_slug))
    if isinstance(caller, SystemCliCaller):
        return identity.role
    if identity.email is not None:
        return HUMAN_ROLE_CUSTOMER
    return None


def caller_for_role_resolution(identity: CallerIdentity) -> CliCaller:
    """Hydrate a carried person identity with its roster slug for scoped role lookup."""
    caller = caller_from_carried_identity(identity)
    if not isinstance(caller, PersonCliCaller):
        return caller
    principal = identity.principal or (human_principal_for_email(identity.email) if identity.email else None)
    resolved = caller_from_principal(principal)
    if not isinstance(resolved, PersonCliCaller):
        return caller
    return PersonCliCaller(email=caller.email, person_slug=resolved.person_slug, human_role=caller.human_role)


def caller_from_carried_identity(identity: CallerIdentity) -> CliCaller:
    """Adapt carried identity to the shared caller type without re-resolving it."""
    principal = identity.principal
    if principal and principal.startswith("human:"):
        email = identity.email or principal.removeprefix("human:")
        return PersonCliCaller(email=email, human_role=identity.human_role)
    if principal and principal.startswith("system:"):
        return SystemCliCaller()
    if identity.email is not None or identity.human_role is not None:
        return PersonCliCaller(email=identity.email, human_role=identity.human_role)
    if identity.role is not None:
        return SystemCliCaller()
    return NoIdentityCliCaller()


def principal_for_carried_caller(identity: CallerIdentity, *, required: bool = False) -> str | None:
    """Return the principal the client carried, without a daemon lookup."""
    principal = identity.principal
    if required and not principal:
        raise HTTPException(status_code=403, detail=LOGIN_REQUIRED_DETAIL)
    return principal


def carried_caller(
    request: HTTPConnection,
    x_teleclaude_daemon_token: Annotated[str | None, Header()] = None,
) -> CallerIdentity:
    """Take the caller identity carried by a client; only the daemon token is verified."""
    if x_teleclaude_daemon_token and is_daemon_credential(x_teleclaude_daemon_token):
        return CallerIdentity(
            session_id="",
            role=None,
            human_role=None,
            principal=SYSTEM_DAEMON_PRINCIPAL,
            entry_point=EntryPoint.AGENT,
        )

    return caller_identity_of(CarriedIdentity.from_headers(request.headers))


def caller_identity_of(carried: CarriedIdentity) -> CallerIdentity:
    """Adapt the identity a client carries into the caller this computer judges, as the daemon edge does."""
    entry_point: EntryPoint | None = None
    if carried.entry_point is not None:
        try:
            entry_point = EntryPoint(carried.entry_point)
        except ValueError:
            entry_point = None
    return CallerIdentity(
        session_id=carried.session_id or "",
        role=carried.role,
        human_role=carried.human_role,
        email=carried.email,
        principal=carried.principal,
        entry_point=entry_point,
        company=carried.company,
        command=carried.command,
    )


def carried_caller_of(request: HTTPConnection) -> CallerIdentity:
    """Take the caller identity carried by a request outside a route's dependency injection."""
    return carried_caller(request, request.headers.get(_DAEMON_TOKEN_HEADER))


def carried_caller_session_id(request: HTTPConnection) -> str | None:
    """Return the session id carried by this request, or None for automation."""
    return carried_caller_of(request).session_id or None


def require_clearance(command_path: str) -> Callable[..., CallerIdentity]:
    """Return a route dependency enforcing the CLI verb's declared caller clearance."""

    def _require(identity: CallerIdentity = Depends(carried_caller)) -> CallerIdentity:
        if is_roleless_platform_caller(identity.principal, identity.role):
            return identity
        role = resolve_session_role(identity.role, identity.session_id)
        if not is_command_allowed_for(command_path, role, identity.human_role):
            raise HTTPException(status_code=403, detail=_CLEARANCE_REFUSAL.format(command_path=command_path))
        return identity

    return _require


def require_clearance_at_caller_person(command_path: str) -> Callable[..., CallerIdentity]:
    """Return a route dependency enforcing a verb's band judged at the caller's own person scope.

    ``require_clearance`` is scope-blind: it judges the carried platform role, which refuses a
    registered person who holds none. A verb declared at the caller-person scope is judged by the
    role that person holds at themselves, as the CLI judges it.
    """

    def _require(identity: CallerIdentity = Depends(carried_caller)) -> CallerIdentity:
        if is_roleless_platform_caller(identity.principal, identity.role):
            return identity
        role = resolve_session_role(identity.role, identity.session_id)
        if not is_command_allowed_for(command_path, role, caller_role_at_own_person_scope(identity)):
            raise HTTPException(status_code=403, detail=_CLEARANCE_REFUSAL.format(command_path=command_path))
        return identity

    return _require


def _relayed_caller_provenance(session_id: str) -> CallerProvenance | None:
    """Provenance for a caller session another computer holds, from the address its relay carried.

    The relaying computer carries only the address, so the author is the generic machine author;
    everything else the caller's surface shows about itself stays with that computer.
    """
    relayed = get_relayed_caller()
    if relayed is None or relayed.session_id != session_id:
        return None
    author = resolve_session_event_author(
        session_id=session_id,
        role=None,
        active_agent=None,
        thinking_mode=None,
    )
    return CallerProvenance(
        session_id=session_id,
        computer=relayed.computer,
        author_kind=author.kind.value,
        author_display=author.display,
        agent_runtime=author.agent_runtime,
        thinking_mode=author.thinking_mode,
        machine_role=author.machine_role,
    )


async def resolve_caller_provenance(identity: CallerIdentity) -> CallerProvenance | None:
    """Build session provenance from the caller's session record when present."""
    if not identity.session_id:
        return None
    session = await db.get_session(identity.session_id)
    if session is None:
        return _relayed_caller_provenance(identity.session_id)
    author = resolve_session_event_author(
        session_id=identity.session_id,
        role=session.role,
        active_agent=session.active_agent,
        thinking_mode=session.thinking_mode,
    )
    return CallerProvenance(
        session_id=identity.session_id,
        computer=config.computer.name,
        author_kind=author.kind.value,
        author_display=author.display,
        agent_runtime=author.agent_runtime,
        thinking_mode=author.thinking_mode,
        machine_role=author.machine_role,
        job_role=session.role,
    )


__all__ = [
    "CallerIdentity",
    "caller_from_carried_identity",
    "carried_caller",
    "carried_caller_of",
    "carried_caller_session_id",
    "principal_for_carried_caller",
    "require_clearance",
    "require_clearance_at_caller_person",
    "resolve_caller_provenance",
]
