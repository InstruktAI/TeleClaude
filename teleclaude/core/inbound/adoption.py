"""Seeding the master's conversation bindings from each computer's own records, and closing orphans.

On adapters whose inbound messages reach every computer, the master routes
from its own durable binding record. Every computer exports its open
conversation sessions from its own database; the master binds each
conversation to its newest open session. The adoption run (the expected
sources each answering once) is the precondition for the cutover in
``teleclaude.core.inbound.cutover``, which takes the authoritative export
again once no computer handles these conversations on its own any more. A
session a lost remote-create answer may have left on its host is never
bound, and is closed by id once that host is live again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

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
    from teleclaude.core.inbound.models import ConversationRef

logger = get_logger(__name__)

# The peer request that answers with a computer's open conversation sessions.
EXPORT_CONVERSATION_SESSIONS_COMMAND = "export_conversation_sessions"
DISCORD_DM_KEY_FIELD = "channel_id"
WHATSAPP_KEY_FIELD = "phone_number"

_ORIGIN_FIELD = "origin"
_KEY_FIELD_FIELD = "key_field"
_KEY_FIELD = "key"
_SESSION_ID_FIELD = "session_id"
_CREATED_AT_FIELD = "created_at"
_ENDPOINT_FIELD = "endpoint"
_ADOPTION_PENDING_EVENT = "conversation_adoption_pending"
_ADOPTION_CONFLICT_EVENT = "adoption_conflict"
_ADOPTION_SOURCE_ANSWERED_EVENT = "conversation_adoption_source_answered"
_ADOPTION_SKIPPED_EVENT = "conversation_adoption_session_skipped"
_ORPHAN_CLOSED_EVENT = "conversation_binding_orphan_closed"
_ORPHAN_CLOSE_FAILED_EVENT = "conversation_binding_orphan_close_failed"
_EXPORT_MALFORMED_EVENT = "conversation_export_malformed"
# A session with no recorded creation time counts as older than every other.
_UNKNOWN_CREATION = datetime.min.replace(tzinfo=UTC)


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
        if not isinstance(created_at, str) or parse_instant(created_at) is None:
            return None
        origin, key_field, key, session_id = cast(list[str], values)
        return ExportedConversationSession(
            origin=origin,
            key_field=key_field,
            key=key,
            session_id=session_id,
            created_at=created_at,
            endpoint=endpoint,
        )


def _instant_or_oldest(text: str) -> datetime:
    return parse_instant(text) or _UNKNOWN_CREATION


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
                created_at=(session.created_at or _UNKNOWN_CREATION).isoformat(),
                endpoint=endpoint,
            )
        )
    return exported


def parse_exported_sessions(payload: object) -> list[ExportedConversationSession] | None:
    """Decode an export answer; ``None`` when any part of it is malformed.

    A malformed answer is no answer: it never completes adoption, and never
    says a session is closed.
    """
    if not isinstance(payload, list):
        return None
    sessions: list[ExportedConversationSession] = []
    for item in payload:
        session = ExportedConversationSession.from_dict(item) if isinstance(item, dict) else None
        if session is None:
            logger.warning(_EXPORT_MALFORMED_EVENT)
            return None
        sessions.append(session)
    return sessions


def parse_instant(text: str) -> datetime | None:
    """An ISO-8601 timestamp as an aware instant (naive means UTC); ``None`` when it is not one."""
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        return None
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


async def adoption_complete(db: Db) -> bool:
    """Whether every expected source has exported; an empty source set is not complete."""
    sources = await db.list_conversation_adoption_sources()
    return bool(sources) and all(source.answered_at is not None for source in sources)


async def seed_bindings(db: Db, host: str, exported: Sequence[ExportedConversationSession]) -> None:
    """Bind each conversation to its newest open session; older ones stay unbound and are logged."""
    for item in sorted(exported, key=lambda session: _instant_or_oldest(session.created_at)):
        current = await db.get_conversation_binding(item.origin, item.key_field, item.key)
        if current is not None and _instant_or_oldest(current.entered_at) > _instant_or_oldest(item.created_at):
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


async def run_adoption_pass(env: ConversationEnvironment) -> bool:
    """Ask every pending expected source that is live for its open conversation sessions.

    Returns whether every expected source has answered.
    """
    sources = await env.db.list_conversation_adoption_sources()
    pending = [source.computer for source in sources if source.answered_at is None]
    if not sources or not pending:
        return bool(sources)
    live = {member.name for member in (await env.observe_fleet()).members}
    for computer in pending:
        if computer not in live:
            continue
        exported = await env.export_from(computer, None)
        if exported is None:
            continue
        await seed_bindings(env.db, computer, exported)
        await env.db.mark_conversation_adoption_source_answered(computer, env.now_iso())
        logger.info(_ADOPTION_SOURCE_ANSWERED_EVENT, computer=computer, sessions=len(exported))
    remaining = [
        source.computer for source in await env.db.list_conversation_adoption_sources() if not source.answered_at
    ]
    if remaining:
        logger.info(_ADOPTION_PENDING_EVENT, pending=remaining)
    return not remaining


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


def utc_now_iso() -> str:
    """The current time, as the binding record stores it."""
    return datetime.now(UTC).isoformat()


__all__ = [
    "DISCORD_DM_KEY_FIELD",
    "EXPORT_CONVERSATION_SESSIONS_COMMAND",
    "WHATSAPP_KEY_FIELD",
    "ExportedConversationSession",
    "adoption_complete",
    "export_local_conversation_sessions",
    "is_superseded",
    "parse_exported_sessions",
    "parse_instant",
    "run_adoption_pass",
    "run_orphan_pass",
    "seed_bindings",
    "shared_conversation_of",
    "utc_now_iso",
]
