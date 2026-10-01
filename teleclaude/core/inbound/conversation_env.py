"""What the conversation seam acts through: this computer, its desks, its database and the fleet.

Every collaborator the seam reaches is a field here, so a probe can run the
seam's decisions against scratch roots, a scratch database and recorded
callables. ``default_conversation_environment`` is the daemon's one instance:
its reply gates and conversation locks are process-wide.
"""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from redis.exceptions import RedisError

from teleclaude.cli.config_handlers import get_global_config
from teleclaude.config import config
from teleclaude.config.invitations import find_person_by_invite_token
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.agent_dispatch import AgentDispatchFailure
from teleclaude.core.command_dispatch import RemoteDispatchError, dispatch_command, parse_remote_dispatch_data
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import Db, db
from teleclaude.core.endpoints import LIVE_ROOTS, DeskRoots
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.inbound.adoption import (
    EXPORT_CONVERSATION_SESSIONS_COMMAND,
    ExportedConversationSession,
    export_local_conversation_sessions,
    parse_exported_sessions,
    utc_now_iso,
)
from teleclaude.core.inbound.fleet import FleetView, observe_fleet
from teleclaude.core.inbound.gates import ConversationLocks, CooldownGate
from teleclaude.core.inbound.models import ConversationRef
from teleclaude.core.models import MessageMetadata
from teleclaude.events.envelope import EventVisibility
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.types.commands import CreateSessionCommand, InternalCommand

# How long the master waits for a peer's export answer.
EXPORT_READ_TIMEOUT_S = 5.0

ExportFrom = Callable[[str, ConversationRef | None], Awaitable[list[ExportedConversationSession] | None]]


@dataclass
class ConversationEnvironment:
    """The seam's collaborators on one computer."""

    host: str
    roots: DeskRoots
    db: Db
    observe_fleet: Callable[[], Awaitable[FleetView]]
    create_local: Callable[[CreateSessionCommand], Awaitable[Mapping[str, str]]]
    close_local: Callable[[str], Awaitable[None]]
    dispatch: Callable[[InternalCommand], Awaitable[object]]
    export_from: ExportFrom
    person_workspace: Callable[[str], Path]
    find_invite: Callable[[str], str | None]
    display_name: Callable[[str], str]
    now_iso: Callable[[], str] = utc_now_iso
    neutral_gate: CooldownGate = field(default_factory=CooldownGate)
    unavailable_gate: CooldownGate = field(default_factory=CooldownGate)
    locks: ConversationLocks = field(default_factory=ConversationLocks)


async def _observe_live_fleet() -> FleetView:
    return await observe_fleet(get_command_service().client)


async def _create_local_session(command: CreateSessionCommand) -> Mapping[str, str]:
    return await get_command_service().create_session(command)


async def _request_local_close(session_id: str) -> None:
    """Ask this computer to end one of its sessions through the ordinary close path."""
    event_bus.emit(
        TeleClaudeEvents.SESSION_CLOSE_REQUESTED,
        SessionLifecycleContext(session_id=session_id),
        visibility=EventVisibility.LOCAL,
    )


async def _dispatch_as_daemon(command: InternalCommand) -> object:
    return await dispatch_command(get_command_service().client, command, principal=SYSTEM_DAEMON_PRINCIPAL)


async def _export_from_computer(
    computer: str, conversation: ConversationRef | None
) -> list[ExportedConversationSession] | None:
    """A computer's open conversation sessions from its own database; ``None`` when it cannot answer."""
    if computer == config.computer.name:
        return await export_local_conversation_sessions(db, LIVE_ROOTS, conversation)
    arguments = (
        [conversation.origin.value, conversation.key_field, conversation.key] if conversation is not None else []
    )
    client = get_command_service().client
    try:
        message_id = await client.send_request(
            computer,
            shlex.join([EXPORT_CONVERSATION_SESSIONS_COMMAND, *arguments]),
            MessageMetadata(),
            principal=SYSTEM_DAEMON_PRINCIPAL,
        )
        answer = await client.read_response(message_id, timeout=EXPORT_READ_TIMEOUT_S, target_computer=computer)
        payload = parse_remote_dispatch_data(
            answer, target_computer=computer, command=EXPORT_CONVERSATION_SESSIONS_COMMAND
        )
    except (TimeoutError, OSError, RedisError, RuntimeError, RemoteDispatchError, AgentDispatchFailure):
        return None
    return parse_exported_sessions(payload)


def _invite_holder(token: str) -> str | None:
    found = find_person_by_invite_token(token)
    return found[0] if found is not None else None


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
            roots=LIVE_ROOTS,
            db=db,
            observe_fleet=_observe_live_fleet,
            create_local=_create_local_session,
            close_local=_request_local_close,
            dispatch=_dispatch_as_daemon,
            export_from=_export_from_computer,
            person_workspace=scaffold_personal_workspace,
            find_invite=_invite_holder,
            display_name=_person_display_name,
        )
        _ENVIRONMENT_SLOT[_DEFAULT_ENVIRONMENT_KEY] = environment
    return environment


__all__ = [
    "EXPORT_READ_TIMEOUT_S",
    "ConversationEnvironment",
    "ExportFrom",
    "default_conversation_environment",
]
