"""What the conversation seam acts through: this computer, its desks, its database and the fleet.

Every collaborator the seam reaches is a field here, so a probe can run the
seam's decisions against scratch roots, a scratch database and recorded
callables. ``default_conversation_environment`` is the daemon's one instance:
its reply gates and conversation locks are process-wide.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.caller_identity import (
    PersonCliCaller,
    RoleResolver,
    SessionIdentityError,
    ThisComputer,
    caller_from_principal,
    resolve_session_principal,
)
from teleclaude.cli.config_handlers import get_global_config
from teleclaude.config.invitations import find_person_by_invite_token
from teleclaude.config.machine import config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_close import CloseAdmission, retire_session
from teleclaude.core.db import Db, db
from teleclaude.core.endpoints import LIVE_ROOTS, DeskRoots
from teleclaude.core.identity import IdentityContext
from teleclaude.core.inbound.fleet import FleetView, observe_fleet
from teleclaude.core.inbound.gates import ConversationLocks, CooldownGate
from teleclaude.core.models import Session
from teleclaude.core.session_revival import revive_session
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.types.commands import CreateSessionCommand


def utc_now_iso() -> str:
    """The current time, as the binding record stores it."""
    return datetime.now(UTC).isoformat()


@dataclass
class ConversationEnvironment:
    """The seam's collaborators on one computer."""

    host: str
    is_master: bool
    roots: DeskRoots
    db: Db
    observe_fleet: Callable[[], Awaitable[FleetView]]
    create_local: Callable[[CreateSessionCommand], Awaitable[Mapping[str, str]]]
    revive_local: Callable[[str], Awaitable[bool]]
    effective_role: Callable[[IdentityContext], str]
    person_workspace: Callable[[str], Path]
    find_invite: Callable[[str], str | None]
    display_name: Callable[[str], str]
    session_person: Callable[[Session], str | None]
    retire_session: Callable[[str], Awaitable[CloseAdmission]]
    now_iso: Callable[[], str] = utc_now_iso
    neutral_gate: CooldownGate = field(default_factory=CooldownGate)
    unavailable_gate: CooldownGate = field(default_factory=CooldownGate)
    locks: ConversationLocks = field(default_factory=ConversationLocks)


async def _observe_live_fleet() -> FleetView:
    return await observe_fleet(get_command_service().client)


async def _create_local_session(command: CreateSessionCommand) -> Mapping[str, str]:
    return await get_command_service().create_session(command)


def _effective_role_here(sender: IdentityContext) -> str:
    """The highest role the sender holds on this computer: their platform role and every company membership."""
    caller = PersonCliCaller(email=sender.person_email, person_slug=sender.person_slug, human_role=sender.person_role)
    return RoleResolver().role_for(caller, ThisComputer())


def _invite_holder(token: str) -> str | None:
    found = find_person_by_invite_token(token)
    return found[0] if found is not None else None


async def _retire_session_here(session_id: str) -> CloseAdmission:
    return await retire_session(session_id, get_command_service().client)


def _session_person_here(session: Session) -> str | None:
    """The registered person a session's recorded human principal resolves to, or ``None``."""
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return None
    caller = caller_from_principal(principal)
    return caller.person_slug if isinstance(caller, PersonCliCaller) else None


def _person_display_name(person_slug: str) -> str:
    return next((person.name for person in get_global_config().people if person.slug == person_slug), person_slug)


_ENVIRONMENT_SLOT: dict[str, ConversationEnvironment] = {}
_DEFAULT_ENVIRONMENT_KEY = "default"


def default_conversation_environment() -> ConversationEnvironment:
    """The daemon's conversation environment, created once."""
    environment = _ENVIRONMENT_SLOT.get(_DEFAULT_ENVIRONMENT_KEY)
    if environment is None:
        environment = ConversationEnvironment(
            host=config.computer.name,
            is_master=bool(config.computer.is_master),
            roots=LIVE_ROOTS,
            db=db,
            observe_fleet=_observe_live_fleet,
            create_local=_create_local_session,
            revive_local=revive_session,
            effective_role=_effective_role_here,
            person_workspace=scaffold_personal_workspace,
            find_invite=_invite_holder,
            display_name=_person_display_name,
            session_person=_session_person_here,
            retire_session=_retire_session_here,
        )
        _ENVIRONMENT_SLOT[_DEFAULT_ENVIRONMENT_KEY] = environment
    return environment


__all__ = [
    "ConversationEnvironment",
    "default_conversation_environment",
    "utc_now_iso",
]
