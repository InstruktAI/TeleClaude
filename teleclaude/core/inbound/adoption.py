"""The cutover to master routing, seeding the master's bindings, and closing orphans.

On adapters whose inbound messages reach every computer, the master routes
from its own durable binding record. That record starts from what each
expected computer holds: every computer exports its open conversation
sessions from its own database. Until every expected computer has answered,
nothing changes: each computer keeps handling these conversations as before.
Once they have, the master records the activation and announces it; every
other computer records it on seeing that announcement and stops handling
these conversations, and the master starts routing after a grace period in
which every computer has seen it. The activation is one-way: with the master
down afterwards, nobody routes. A session a lost remote-create answer may have
left on its host is never bound, and is closed by id once that host is live
again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.db import ConversationBinding, Db
from teleclaude.core.endpoints import DeskRoots, platform_help_desk_folder
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import (
    ENDPOINT_SECTION,
    DiscordAdapterMetadata,
    EndpointKind,
    EndpointStamp,
    EndpointStampField,
    HelpDeskKind,
    JsonDict,
    Session,
    WhatsAppAdapterMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_session_terminal
from teleclaude.types.commands import CloseSessionCommand

if TYPE_CHECKING:
    from teleclaude.core.inbound.conversation_env import ConversationEnvironment
    from teleclaude.core.inbound.fleet import FleetView
    from teleclaude.core.inbound.models import ConversationRef

logger = get_logger(__name__)

# The peer request that answers with a computer's open conversation sessions.
EXPORT_CONVERSATION_SESSIONS_COMMAND = "export_conversation_sessions"
DISCORD_DM_KEY_FIELD = "channel_id"
WHATSAPP_KEY_FIELD = "phone_number"
# How often the master retries pending adoption sources and orphan closes.
CONVERSATION_UPKEEP_INTERVAL_S = 30.0
# The system setting recording when shared-adapter routing was activated on this computer.
ROUTING_ACTIVATED_AT_SETTING = "conversation_routing_activated_at"
# The master starts routing this long after recording the activation: longer than
# a heartbeat interval, so every other computer has seen the announcement first.
ROUTING_ACTIVATION_GRACE_S = 75.0

_ORIGIN_FIELD = "origin"
_KEY_FIELD_FIELD = "key_field"
_KEY_FIELD = "key"
_SESSION_ID_FIELD = "session_id"
_CREATED_AT_FIELD = "created_at"
_ENDPOINT_FIELD = "endpoint"
_ADOPTION_PENDING_EVENT = "conversation_adoption_pending"
_ADOPTION_COMPLETE_EVENT = "conversation_bindings_adopted"
_ADOPTION_CONFLICT_EVENT = "adoption_conflict"
_ADOPTION_SOURCE_ANSWERED_EVENT = "conversation_adoption_source_answered"
_ADOPTION_SKIPPED_EVENT = "conversation_adoption_session_skipped"
_ORPHAN_CLOSED_EVENT = "conversation_binding_orphan_closed"
_ORPHAN_CLOSE_FAILED_EVENT = "conversation_binding_orphan_close_failed"
_UPKEEP_FAILED_EVENT = "conversation_upkeep_failed"
_ROUTING_ACTIVATION_OBSERVED_EVENT = "conversation_routing_activation_observed"


class SharedRoutingState(StrEnum):
    """Whether this computer hands shared-adapter conversations to master routing yet."""

    BEFORE_CUTOVER = "before_cutover"
    ACTIVE = "active"


@dataclass(frozen=True)
class ExportedConversationSession:
    """One open session a computer holds for a shared-adapter conversation."""

    origin: str
    key_field: str
    key: str
    session_id: str
    created_at: str
    endpoint: EndpointStamp

    def to_dict(self) -> JsonDict:
        """Serialize for the export answer."""
        return {
            _ORIGIN_FIELD: self.origin,
            _KEY_FIELD_FIELD: self.key_field,
            _KEY_FIELD: self.key,
            _SESSION_ID_FIELD: self.session_id,
            _CREATED_AT_FIELD: self.created_at,
            _ENDPOINT_FIELD: self.endpoint.to_dict(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, object]) -> ExportedConversationSession | None:
        """Rebuild one exported session; a malformed entry is no session."""
        endpoint_raw = data.get(_ENDPOINT_FIELD)
        endpoint = EndpointStamp.from_dict(endpoint_raw) if isinstance(endpoint_raw, dict) else None
        values = [data.get(name) for name in (_ORIGIN_FIELD, _KEY_FIELD_FIELD, _KEY_FIELD, _SESSION_ID_FIELD)]
        created_at = data.get(_CREATED_AT_FIELD)
        if endpoint is None or not all(isinstance(value, str) and value for value in values):
            return None
        origin, key_field, key, session_id = cast(list[str], values)
        return ExportedConversationSession(
            origin=origin,
            key_field=key_field,
            key=key,
            session_id=session_id,
            created_at=created_at if isinstance(created_at, str) else "",
            endpoint=endpoint,
        )


def shared_conversation_of(session: Session) -> tuple[InputOrigin, str, str] | None:
    """The shared-adapter conversation a session belongs to: a Discord DM or a WhatsApp number."""
    discord = DiscordAdapterMetadata.from_dict(session.get_origin_section(InputOrigin.DISCORD.value))
    if discord.channel_id is not None and discord.guild_id is None and discord.thread_id is None and discord.user_id:
        return InputOrigin.DISCORD, DISCORD_DM_KEY_FIELD, str(discord.channel_id)
    whatsapp = WhatsAppAdapterMetadata.from_dict(session.get_origin_section(InputOrigin.WHATSAPP.value))
    if whatsapp.phone_number:
        return InputOrigin.WHATSAPP, WHATSAPP_KEY_FIELD, whatsapp.phone_number
    return None


def is_superseded(session: Session) -> bool:
    """Whether a later entry of the session's conversation took the conversation elsewhere."""
    return session.get_origin_section(ENDPOINT_SECTION).get(EndpointStampField.SUPERSEDED_AT) is not None


def _exported_endpoint(session: Session, origin: InputOrigin, roots: DeskRoots) -> EndpointStamp | None:
    """The endpoint an open session was created at, recovered for sessions that predate the stamp."""
    stamp = EndpointStamp.from_session(session)
    if stamp is not None:
        return stamp
    if session.human_email:
        identity = get_identity_resolver().resolve(origin.value, session.get_origin_section(origin.value))
        return EndpointStamp(kind=EndpointKind.ASSISTANT, person=identity.person_slug)
    if session.confinement_profile is not None and session.project_path:
        if str(platform_help_desk_folder(roots)) == session.project_path:
            return EndpointStamp(kind=EndpointKind.HELP_DESK, desk_kind=HelpDeskKind.PLATFORM)
    return None


async def export_local_conversation_sessions(
    db: Db,
    roots: DeskRoots,
    conversation: ConversationRef | None = None,
) -> list[ExportedConversationSession]:
    """This computer's open shared-adapter conversation sessions, read from its own database.

    Only sessions of a registered person or with a recorded confinement are
    exported; with ``conversation``, only that conversation's.
    """
    exported: list[ExportedConversationSession] = []
    for session in await db.list_sessions(all_open=True):
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            continue
        located = shared_conversation_of(session)
        if located is None or is_superseded(session):
            continue
        origin, key_field, key = located
        if conversation is not None and (origin, key_field, key) != (
            conversation.origin,
            conversation.key_field,
            conversation.key,
        ):
            continue
        endpoint = _exported_endpoint(session, origin, roots)
        if endpoint is None:
            logger.info(_ADOPTION_SKIPPED_EVENT, session_id=session.session_id, origin=origin.value)
            continue
        exported.append(
            ExportedConversationSession(
                origin=origin.value,
                key_field=key_field,
                key=key,
                session_id=session.session_id,
                created_at=session.created_at.isoformat() if session.created_at else "",
                endpoint=endpoint,
            )
        )
    return exported


def parse_exported_sessions(payload: object) -> list[ExportedConversationSession]:
    """Decode an export answer, dropping malformed entries."""
    if not isinstance(payload, list):
        return []
    sessions = (ExportedConversationSession.from_dict(item) for item in payload if isinstance(item, dict))
    return [session for session in sessions if session is not None]


async def shared_routing_activated(db: Db) -> bool:
    """Whether shared-adapter routing has been activated on this computer."""
    return await db.get_system_setting(ROUTING_ACTIVATED_AT_SETTING) is not None


async def shared_routing_state(env: ConversationEnvironment, fleet: FleetView) -> SharedRoutingState:
    """This computer's side of the cutover to master routing.

    The master activates when every expected source has exported; another
    computer activates when it first sees the master announce it. Before that,
    each computer handles these conversations itself, as before the cutover.
    """
    activated_at = await env.db.get_system_setting(ROUTING_ACTIVATED_AT_SETTING)
    now = datetime.fromisoformat(env.now_iso())
    if activated_at is not None:
        if not fleet.local.is_master:
            return SharedRoutingState.ACTIVE
        routing_from = datetime.fromisoformat(activated_at) + timedelta(seconds=ROUTING_ACTIVATION_GRACE_S)
        return SharedRoutingState.ACTIVE if now >= routing_from else SharedRoutingState.BEFORE_CUTOVER
    master = fleet.master()
    if fleet.local.is_master or master is None or not master.routing_active:
        return SharedRoutingState.BEFORE_CUTOVER
    await env.db.set_system_setting(ROUTING_ACTIVATED_AT_SETTING, now.isoformat())
    logger.info(_ROUTING_ACTIVATION_OBSERVED_EVENT, master=master.name)
    return SharedRoutingState.ACTIVE


async def adoption_complete(db: Db) -> bool:
    """Whether every expected source has exported; an empty source set is not complete."""
    sources = await db.list_conversation_adoption_sources()
    return bool(sources) and all(source.answered_at is not None for source in sources)


async def _seed(db: Db, host: str, exported: Sequence[ExportedConversationSession]) -> None:
    """Bind each conversation to its newest open session; older ones stay unbound and are logged."""
    for item in sorted(exported, key=lambda session: session.created_at):
        current = await db.get_conversation_binding(item.origin, item.key_field, item.key)
        if current is not None and current.entered_at > item.created_at:
            logger.warning(_ADOPTION_CONFLICT_EVENT, origin=item.origin, unbound_session_id=item.session_id)
            continue
        if current is not None and current.session_id != item.session_id:
            logger.warning(_ADOPTION_CONFLICT_EVENT, origin=item.origin, unbound_session_id=current.session_id)
        await db.put_conversation_binding(
            ConversationBinding(
                origin=item.origin,
                key_field=item.key_field,
                conversation_key=item.key,
                host=host,
                session_id=item.session_id,
                endpoint=item.endpoint,
                entered_at=item.created_at,
            )
        )


async def _activate_when_adopted(env: ConversationEnvironment) -> None:
    """Record the master's activation once every expected source has answered."""
    if await adoption_complete(env.db) and not await shared_routing_activated(env.db):
        await env.db.set_system_setting(ROUTING_ACTIVATED_AT_SETTING, env.now_iso())
        logger.info(_ADOPTION_COMPLETE_EVENT)


async def run_adoption_pass(env: ConversationEnvironment) -> None:
    """Ask every pending expected source that is live for its open conversation sessions."""
    sources = await env.db.list_conversation_adoption_sources()
    pending = [source.computer for source in sources if source.answered_at is None]
    if not sources or not pending:
        await _activate_when_adopted(env)
        return
    live = {member.name for member in (await env.observe_fleet()).members}
    for computer in pending:
        if computer not in live:
            continue
        exported = await env.export_from(computer, None)
        if exported is None:
            continue
        await _seed(env.db, computer, exported)
        await env.db.mark_conversation_adoption_source_answered(computer, env.now_iso())
        logger.info(_ADOPTION_SOURCE_ANSWERED_EVENT, computer=computer, sessions=len(exported))
    remaining = [
        source.computer for source in await env.db.list_conversation_adoption_sources() if not source.answered_at
    ]
    if remaining:
        logger.info(_ADOPTION_PENDING_EVENT, pending=remaining)
    await _activate_when_adopted(env)


async def run_orphan_pass(env: ConversationEnvironment) -> None:
    """Close every remembered orphan session whose host is live again, by its exact id."""
    orphans = await env.db.list_conversation_binding_orphans()
    if not orphans:
        return
    live = {member.name for member in (await env.observe_fleet()).members}
    for orphan in orphans:
        if orphan.host not in live:
            continue
        command = CloseSessionCommand(session_id=orphan.session_id)
        command.computer = orphan.host
        try:
            await env.dispatch(command)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning(_ORPHAN_CLOSE_FAILED_EVENT, session_id=orphan.session_id, host=orphan.host, error=str(exc))
            continue
        await env.db.delete_conversation_binding_orphan(orphan.session_id)
        logger.info(_ORPHAN_CLOSED_EVENT, session_id=orphan.session_id, host=orphan.host)


async def run_conversation_upkeep(env: ConversationEnvironment, shutdown_event: asyncio.Event) -> None:
    """Every interval: the master retries pending adoption sources and orphan closes; another
    computer records the master's activation as soon as the master announces it, so it stops
    handling these conversations itself even if the master is down by the next one.
    """
    while not shutdown_event.is_set():
        try:
            if config.computer.is_master:
                await run_adoption_pass(env)
                await run_orphan_pass(env)
            else:
                await shared_routing_state(env, await env.observe_fleet())
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error(_UPKEEP_FAILED_EVENT, error=str(exc), exc_info=True)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CONVERSATION_UPKEEP_INTERVAL_S)
        except TimeoutError:
            continue


def utc_now_iso() -> str:
    """The current time, as the binding record stores it."""
    return datetime.now(UTC).isoformat()


__all__ = [
    "CONVERSATION_UPKEEP_INTERVAL_S",
    "DISCORD_DM_KEY_FIELD",
    "EXPORT_CONVERSATION_SESSIONS_COMMAND",
    "ROUTING_ACTIVATED_AT_SETTING",
    "ROUTING_ACTIVATION_GRACE_S",
    "WHATSAPP_KEY_FIELD",
    "ExportedConversationSession",
    "SharedRoutingState",
    "adoption_complete",
    "export_local_conversation_sessions",
    "is_superseded",
    "parse_exported_sessions",
    "run_adoption_pass",
    "run_conversation_upkeep",
    "run_orphan_pass",
    "shared_conversation_of",
    "shared_routing_activated",
    "shared_routing_state",
    "utc_now_iso",
]
