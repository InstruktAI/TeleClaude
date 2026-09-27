"""Daemon intake for client-carried identity and caller provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, Request

from teleclaude.caller_identity import (
    CarriedIdentity,
    CliCaller,
    NoIdentityCliCaller,
    PersonCliCaller,
    SystemCliCaller,
)
from teleclaude.config import config
from teleclaude.constants import ROLE_SYSTEM, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.conversation_messages import resolve_session_event_author
from teleclaude.core.daemon_lifecycle_identity import is_daemon_credential
from teleclaude.core.db import db
from teleclaude.types.commands import CallerProvenance
from teleclaude.types.creation_record import EntryPoint


@dataclass(frozen=True)
class CallerIdentity:
    """Identity the request's client resolved and carried to the daemon."""

    session_id: str
    system_role: str | None
    human_role: str | None
    email: str | None = None
    principal: str | None = None
    entry_point: EntryPoint | None = None
    company: str | None = None


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
    if identity.system_role is not None:
        return SystemCliCaller()
    return NoIdentityCliCaller()


def principal_for_carried_caller(identity: CallerIdentity) -> str | None:
    """Return the principal the client carried, without a daemon lookup."""
    return identity.principal


def carried_caller(
    request: Request,
    x_teleclaude_daemon_token: Annotated[str | None, Header()] = None,
) -> CallerIdentity:
    """Take the caller identity carried by a client; only the daemon token is verified."""
    if x_teleclaude_daemon_token and is_daemon_credential(x_teleclaude_daemon_token):
        return CallerIdentity(
            session_id="",
            system_role=ROLE_SYSTEM,
            human_role=None,
            principal=SYSTEM_DAEMON_PRINCIPAL,
            entry_point=EntryPoint.AGENT,
        )

    carried = CarriedIdentity.from_headers(request.headers)
    entry_point: EntryPoint | None = None
    if carried.entry_point is not None:
        try:
            entry_point = EntryPoint(carried.entry_point)
        except ValueError:
            entry_point = None
    return CallerIdentity(
        session_id=carried.session_id or "",
        system_role=carried.system_role,
        human_role=carried.human_role,
        email=carried.email,
        principal=carried.principal,
        entry_point=entry_point,
        company=carried.company,
    )


async def resolve_caller_provenance(identity: CallerIdentity) -> CallerProvenance | None:
    """Build session provenance from the caller's session record when present."""
    if not identity.session_id:
        return None
    session = await db.get_session(identity.session_id)
    if session is None:
        return None
    author = resolve_session_event_author(
        session_id=identity.session_id,
        system_role=session.system_role,
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
        job_role=session.job,
    )


__all__ = [
    "CallerIdentity",
    "caller_from_carried_identity",
    "carried_caller",
    "principal_for_carried_caller",
    "resolve_caller_provenance",
]
