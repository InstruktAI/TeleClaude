"""The help-desk escalation relay: who an escalation reaches, and the relay between them and the visitor.

Escalation is a help-desk act (`projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`).
It reaches the admins of the home that owns the desk, each in their own
conversation with the platform, and falls back to the platform's admins.
While the relay is active the visitor's input goes to those admins instead of
the agent; an admin answers by replying to any relay message they received,
and a reply that tags the agent hands the exchange back to the same session.
A platform desk's escalation also opens a thread in the shared escalation
forum, where any post answers.

Adapters only extract an admin's reply (`AdminReply`); the conversation seam
offers it here before routing, and the session's own message pipeline offers
the visitor's input.
"""

from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import TypedDict
from uuid import uuid4

import httpx
from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.config.schema import MessagingChannel
from teleclaude.constants import HUMAN_ROLE_ADMIN, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.adapter_errors import AdapterError
from teleclaude.core.agent_dispatch import AgentDispatchFailure
from teleclaude.core.command_dispatch import RemoteDispatchError, parse_remote_dispatch_data
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.endpoints import LIVE_ROOTS, DeskRoots
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload
from teleclaude.core.identity import derive_identity_key, session_person_role
from teleclaude.core.inbound.fleet import FleetView, observe_fleet
from teleclaude.core.injected_text import EnvelopeName, semantic_envelope
from teleclaude.core.models import (
    EndpointStamp,
    HelpDeskKind,
    MessageMetadata,
    RelayExchangeEntry,
    RelayExchangeRole,
    RelayStatus,
    RelayTarget,
    Session,
    encode_relay_exchange,
    encode_relay_targets,
)
from teleclaude.core.organization import company_admin_slugs, platform_admin_people
from teleclaude.core.person_messaging import (
    PersonMessageOutcome,
    ResolvedPersonChannel,
    resolve_person_channel,
    send_person_message,
)
from teleclaude.core.protocols import AdminReflectionAdapter
from teleclaude.core.reconciliation import HELP_DESK_RELAY_FEATURE_ID
from teleclaude.core.relay_context import compile_relay_context
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.events.envelope import EventVisibility
from teleclaude.services.project_catalog.service import ProjectCatalogService

logger = get_logger(__name__)

ESCALATION_NOT_A_DESK = "Escalation is a help-desk act: this session runs in no help desk"
ESCALATION_BY_ADMIN = "Admins are the escalation target and do not escalate"
ESCALATION_NOT_AVAILABLE = "Escalation is not available for this desk yet"
ESCALATION_ALREADY_ACTIVE = "This conversation is already escalated"
ESCALATION_SESSION_NOT_ACTIVE = "Escalation needs an active session"
ESCALATION_UNDELIVERED = "The escalation did not happen: no admin could be notified"
RELAY_RESEND_REPLY = "Couldn't match your reply right now; please resend."
OWNER_QUERY_REFUSED = "relay reply ownership is answered only to a peer daemon"

RELAY_REPLY_OWNER_COMMAND = "relay_reply_owner"
# How long the asking computer waits for a peer's ownership answer.
RELAY_REPLY_OWNER_TIMEOUT_S = 3.0
# How long an answered admin message is remembered, so a reply delivered twice is answered once.
_ANSWERED_REPLY_TTL_S = 600.0
_AGENT_TAG = "@agent"
_ACCEPTED_STATUS = "accepted"
_HASHED_IDENTITY_LENGTH = 16
_RELAY_OCCURRENCE_TEMPLATE = "relay:{session_id}:{nonce}"
_ANSWERED_KEY_TEMPLATE = "{channel}:{message_id}"

_PLATFORM_DESK_LABEL = "the platform help desk"
_TENANT_DESK_LABEL_TEMPLATE = "the {kind}/{slug} help desk"
_UNKNOWN_ORIGIN = "unknown channel"
_UNKNOWN_IDENTITY = "unknown"
_VISITOR_LABEL = "Visitor"
_ADMIN_LABEL = "Admin"
_ESCALATION_HEADER_TEMPLATE = "Escalation from {desk}"
_ESCALATION_VISITOR_TEMPLATE = "Visitor: {name} ({origin}, {identity})"
_ESCALATION_REASON_TEMPLATE = "Reason: {reason}"
_ESCALATION_SUMMARY_TEMPLATE = "Summary: {summary}"
_ESCALATION_SECTION_SEPARATOR = "\n"
_REPLY_GUIDANCE = "Reply to this message to answer; reply with @agent to hand back."
_EMAIL_GUIDANCE = (
    "You can't answer by email. Set Telegram, Discord or WhatsApp as your preferred channel to answer escalations."
)
_FORWARD_TEMPLATE = "{name} ({origin}): {text}"
_FILE_NOTICE_TEMPLATE = "sent a file: {filename}"
_ADMIN_ANSWER_TEMPLATE = "{name}: {text}"

_ESCALATED_EVENT = "session.escalation_started"
_ESCALATION_ENDED_EVENT = "session.escalation_ended"
_RECIPIENT_FAILED_EVENT = "help_desk_escalation_recipient_failed"
_FALLBACK_EVENT = "help_desk_escalation_platform_fallback"
_THREAD_FAILED_EVENT = "help_desk_escalation_thread_failed"
_ESCALATED_LOG_EVENT = "help_desk_escalated"
_FORWARD_FAILED_EVENT = "help_desk_relay_forward_failed"
_ANSWERED_EVENT = "help_desk_relay_answered"
_HANDED_BACK_EVENT = "help_desk_relay_handed_back"
_DELIVERY_FAILED_EVENT = "help_desk_relay_visitor_delivery_failed"
_OWNER_UNCERTAIN_EVENT = "relay_reply_owner_uncertain"
_OWNED_ELSEWHERE_EVENT = "relay_reply_owned_elsewhere"
_OWNER_QUERY_REFUSED_EVENT = "relay_reply_owner_query_refused"

# Failures of one person-addressed send: unknown person, no credential, provider refusal.
_SEND_ERRORS = (ValueError, RuntimeError, OSError, httpx.HTTPError)
_PEER_ERRORS = (TimeoutError, OSError, RedisError, RuntimeError, RemoteDispatchError, AgentDispatchFailure)


class EscalationOutcome(TypedDict):
    """An accepted escalation: how many admins were notified, and the shared thread if one opened."""

    status: str
    notified: int
    thread_id: str | None


class EscalationRefused(ValueError):
    """The session may not escalate; no admin is notified and no relay starts."""


class EscalationUndelivered(ValueError):
    """No admin could be notified; the escalation did not happen."""


class RelayOwnerAnswer(StrEnum):
    """A computer's answer to whether it holds the relay a reply answers."""

    OWNED = "owned"
    NONE = "none"


class RelayReplyDisposition(StrEnum):
    """What became of a reply to one of the platform's messages, once the fleet was asked."""

    OWNED_ELSEWHERE = "owned_elsewhere"
    UNCERTAIN = "uncertain"
    NOT_RELAY = "not_relay"


@dataclass(frozen=True)
class EscalationRequest:
    """What the desk agent supplies: the visitor's name, the reason and an optional summary."""

    customer_name: str
    reason: str
    summary: str = ""


@dataclass(frozen=True)
class AdminReply:
    """A reply in a person's own conversation with the platform, as an adapter extracted it.

    ``target`` is that conversation's address on ``channel`` (the address a
    relay message was sent to), ``replied_message_id`` the platform message
    replied to, and ``admin_message_id`` the reply itself.
    """

    channel: MessagingChannel
    target: str
    replied_message_id: str
    admin_message_id: str
    admin_name: str

    def command_arguments(self, text: str) -> list[str]:
        """The arguments of the ownership query that carries this reply."""
        return [self.channel.value, self.target, self.replied_message_id, self.admin_message_id, self.admin_name, text]

    @classmethod
    def from_command_arguments(cls, arguments: list[str]) -> tuple[AdminReply, str] | None:
        """The reply and its text from an ownership query; malformed arguments are none."""
        if len(arguments) != _OWNER_QUERY_ARGUMENT_COUNT:
            return None
        channel, target, replied, own_id, name, text = arguments
        try:
            return cls(MessagingChannel(channel), target, replied, own_id, name), text
        except ValueError:
            return None


_OWNER_QUERY_ARGUMENT_COUNT = 6

SendToPerson = Callable[..., Awaitable[PersonMessageOutcome]]
AskPeer = Callable[[str, AdminReply, str], Awaitable[RelayOwnerAnswer | None]]


@dataclass
class RelayEnvironment:
    """What the relay acts through; probes replace any of it."""

    send_to_person: SendToPerson
    resolve_channel: Callable[[str], ResolvedPersonChannel]
    owning_admins: Callable[[EndpointStamp], list[str]]
    platform_admins: Callable[[], list[str]]
    admin_adapter: Callable[[], AdminReflectionAdapter | None]
    deliver_to_visitor: Callable[[Session, str], Awaitable[None]]
    observe_fleet: Callable[[], Awaitable[FleetView]]
    ask_peer: AskPeer
    answered: dict[str, float] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock_for(self, session_id: str) -> asyncio.Lock:
        """The one lock that orders every write to a session's relay record."""
        return self.locks.setdefault(session_id, asyncio.Lock())


# --------------------------------------------------------------------------
# Recipients
# --------------------------------------------------------------------------


def owning_admins(stamp: EndpointStamp, roots: DeskRoots = LIVE_ROOTS) -> list[str]:
    """The admins of the home that owns a desk; none when the platform's admins own it.

    A company desk's are the company roster's admins; a project desk's are its
    owning company's admins, else its owning person. The platform desk and an
    ownerless project have no owning admins of their own.
    """
    if stamp.desk_kind is HelpDeskKind.COMPANY and stamp.slug:
        return company_admin_slugs(stamp.slug, roots.companies_root)
    if stamp.desk_kind is HelpDeskKind.PROJECT and stamp.slug:
        project = ProjectCatalogService(manifest_path=roots.projects_manifest).get_by_slug(stamp.slug)
        owner_company = project.config.company if project is not None else None
        owner_person = project.config.person if project is not None else None
        admins = company_admin_slugs(owner_company, roots.companies_root) if owner_company else []
        if admins:
            return admins
        if owner_person:
            return [owner_person]
    return []


def platform_admin_slugs() -> list[str]:
    """The platform's admins, in roster order."""
    return [slug for slug, _person_config in platform_admin_people()]


def _local_admin_adapter() -> AdminReflectionAdapter | None:
    for adapter in get_command_service().client.adapters.values():
        if isinstance(adapter, AdminReflectionAdapter):
            return adapter
    return None


async def _send_to_visitor(session: Session, text: str) -> None:
    await get_command_service().client.send_message(
        session=session, text=text, metadata=MessageMetadata(), ephemeral=False
    )


async def _observe_live_fleet() -> FleetView:
    return await observe_fleet(get_command_service().client)


async def _ask_peer(computer: str, reply: AdminReply, text: str) -> RelayOwnerAnswer | None:
    """Ask one peer whether it holds the relay a reply answers; ``None`` when it cannot tell."""
    client = get_command_service().client
    try:
        request_id = await client.send_request(
            computer,
            shlex.join([RELAY_REPLY_OWNER_COMMAND, *reply.command_arguments(text)]),
            MessageMetadata(),
            principal=SYSTEM_DAEMON_PRINCIPAL,
        )
        answer = await client.read_response(request_id, timeout=RELAY_REPLY_OWNER_TIMEOUT_S, target_computer=computer)
        payload = parse_remote_dispatch_data(answer, target_computer=computer, command=RELAY_REPLY_OWNER_COMMAND)
    except _PEER_ERRORS:
        return None
    try:
        return RelayOwnerAnswer(str(payload))
    except ValueError:
        return None


_ENVIRONMENT_SLOT: dict[str, RelayEnvironment] = {}
_DEFAULT_ENVIRONMENT_KEY = "default"


def default_relay_environment() -> RelayEnvironment:
    """The daemon's relay environment, created once."""
    environment = _ENVIRONMENT_SLOT.get(_DEFAULT_ENVIRONMENT_KEY)
    if environment is None:
        environment = RelayEnvironment(
            send_to_person=send_person_message,
            resolve_channel=resolve_person_channel,
            owning_admins=owning_admins,
            platform_admins=platform_admin_slugs,
            admin_adapter=_local_admin_adapter,
            deliver_to_visitor=_send_to_visitor,
            observe_fleet=_observe_live_fleet,
            ask_peer=_ask_peer,
        )
        _ENVIRONMENT_SLOT[_DEFAULT_ENVIRONMENT_KEY] = environment
    return environment


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------


def _desk_label(stamp: EndpointStamp) -> str:
    if stamp.is_platform_desk or stamp.desk_kind is None:
        return _PLATFORM_DESK_LABEL
    return _TENANT_DESK_LABEL_TEMPLATE.format(kind=stamp.desk_kind.value, slug=stamp.slug or "")


def _visitor_origin(session: Session) -> str:
    return session.last_input_origin or _UNKNOWN_ORIGIN


def _visitor_key(session: Session) -> str | None:
    return derive_identity_key(session.origin_metadata)


def _hashed_identity(session: Session) -> str:
    key = _visitor_key(session)
    return sha256(key.encode()).hexdigest()[:_HASHED_IDENTITY_LENGTH] if key else _UNKNOWN_IDENTITY


def _escalation_text(session: Session, stamp: EndpointStamp, request: EscalationRequest, guidance: str) -> str:
    lines = [
        _ESCALATION_HEADER_TEMPLATE.format(desk=_desk_label(stamp)),
        _ESCALATION_VISITOR_TEMPLATE.format(
            name=request.customer_name, origin=_visitor_origin(session), identity=_hashed_identity(session)
        ),
        _ESCALATION_REASON_TEMPLATE.format(reason=request.reason),
    ]
    if request.summary.strip():
        lines.append(_ESCALATION_SUMMARY_TEMPLATE.format(summary=request.summary))
    lines.append(guidance)
    return _ESCALATION_SECTION_SEPARATOR.join(lines)


async def _notify(
    people: Iterable[str],
    session: Session,
    stamp: EndpointStamp,
    request: EscalationRequest,
    env: RelayEnvironment,
) -> tuple[int, list[RelayTarget]]:
    """Notify each person in their own conversation; the count reached, and the targets that can answer."""
    reached = 0
    targets: list[RelayTarget] = []
    for person in people:
        try:
            resolved = env.resolve_channel(person)
            guidance = _EMAIL_GUIDANCE if resolved.channel is MessagingChannel.EMAIL else _REPLY_GUIDANCE
            text = _escalation_text(session, stamp, request, guidance)
            outcome = await env.send_to_person(
                person, text, channel=resolved.channel, origin_session_id=session.session_id
            )
        except _SEND_ERRORS as exc:
            logger.warning(_RECIPIENT_FAILED_EVENT, session_id=session.session_id, person=person, error=str(exc))
            continue
        reached += 1
        if outcome.message_id:
            targets.append(RelayTarget(person, outcome.channel.value, resolved.target, (outcome.message_id,)))
    return reached, targets


async def _open_thread(session: Session, request: EscalationRequest, env: RelayEnvironment) -> str | None:
    adapter = env.admin_adapter()
    if adapter is None:
        return None
    try:
        thread_id = await adapter.create_escalation_thread(
            customer_name=request.customer_name,
            reason=request.reason,
            context_summary=request.summary,
            session_id=session.session_id,
        )
    except AdapterError as exc:
        logger.warning(_THREAD_FAILED_EVENT, session_id=session.session_id, error=str(exc))
        return None
    return str(thread_id)


def _private_targets_allowed(fleet: FleetView) -> bool:
    """Whether every live computer intercepts relay replies, so admins may be addressed privately."""
    return fleet.capability_map().safe_to_require(HELP_DESK_RELAY_FEATURE_ID)


async def escalate(
    session: Session, request: EscalationRequest, env: RelayEnvironment | None = None
) -> EscalationOutcome:
    """Escalate a help-desk session to the admins of the home that owns its desk.

    Raises ``EscalationRefused`` outside a help desk, for an admin, for a
    session already relaying or not active, and ``EscalationUndelivered`` when
    nobody could be notified; neither leaves relay state behind.
    """
    environment = env if env is not None else default_relay_environment()
    stamp = EndpointStamp.from_session(session)
    if stamp is None or not stamp.is_help_desk:
        raise EscalationRefused(ESCALATION_NOT_A_DESK)
    if session_person_role(session) == HUMAN_ROLE_ADMIN:
        raise EscalationRefused(ESCALATION_BY_ADMIN)
    if session.relay_status == RelayStatus.ACTIVE:
        raise EscalationRefused(ESCALATION_ALREADY_ACTIVE)
    if session.lifecycle_status != SessionLifecycleStatus.ACTIVE.value:
        raise EscalationRefused(ESCALATION_SESSION_NOT_ACTIVE)

    private = _private_targets_allowed(await environment.observe_fleet())
    if not private and not stamp.is_platform_desk:
        raise EscalationRefused(ESCALATION_NOT_AVAILABLE)

    reached: int = 0
    targets: list[RelayTarget] = []
    if private:
        owners = environment.owning_admins(stamp)
        reached, targets = await _notify(owners or environment.platform_admins(), session, stamp, request, environment)
        if reached == 0 and owners:
            logger.info(_FALLBACK_EVENT, session_id=session.session_id, desk=_desk_label(stamp))
            reached, targets = await _notify(environment.platform_admins(), session, stamp, request, environment)
    thread_id = await _open_thread(session, request, environment) if stamp.is_platform_desk else None
    if reached == 0 and thread_id is None:
        raise EscalationUndelivered(ESCALATION_UNDELIVERED)

    await db.update_session(
        session.session_id,
        relay_status=RelayStatus.ACTIVE.value,
        relay_channel_id=thread_id,
        relay_started_at=datetime.now(UTC).isoformat(),
    )
    await db.update_session(
        session.session_id, relay_targets=encode_relay_targets(tuple(targets)), relay_exchange=encode_relay_exchange(())
    )
    await transition_session(
        db,
        session.session_id,
        LifecycleTransition(SessionLifecycleStatus.ESCALATED, LifecycleTransitionReason.ESCALATED),
    )
    event_bus.emit(
        _ESCALATED_EVENT,  # type: ignore[arg-type]
        SessionEscalatedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )
    logger.info(
        _ESCALATED_LOG_EVENT,
        session_id=session.session_id,
        desk=_desk_label(stamp),
        notified=reached,
        answerable=len(targets),
        thread=thread_id is not None,
    )
    return EscalationOutcome(status=_ACCEPTED_STATUS, notified=reached, thread_id=thread_id)


# --------------------------------------------------------------------------
# Visitor → admins
# --------------------------------------------------------------------------


def is_visitor_input(session: Session, actor_id: str | None, caller_session_id: str | None) -> bool:
    """Whether input to a relaying session comes from its visitor, and so goes to the admins."""
    if session.relay_status != RelayStatus.ACTIVE or caller_session_id is not None or not actor_id:
        return False
    return actor_id == _visitor_key(session)


async def _forward(session: Session, label: str, text: str, env: RelayEnvironment) -> tuple[RelayTarget, ...]:
    """Forward one visitor message to every relay target; the targets with the new message ids recorded."""
    forwarded = _FORWARD_TEMPLATE.format(name=label, origin=_visitor_origin(session), text=text)
    updated: list[RelayTarget] = []
    for target in session.relay_targets:
        try:
            outcome = await env.send_to_person(
                target.person, forwarded, channel=MessagingChannel(target.channel), origin_session_id=session.session_id
            )
        except _SEND_ERRORS as exc:
            logger.warning(_FORWARD_FAILED_EVENT, session_id=session.session_id, person=target.person, error=str(exc))
            updated.append(target)
            continue
        updated.append(target.with_message(outcome.message_id) if outcome.message_id else target)
    adapter = env.admin_adapter() if session.relay_channel_id else None
    if session.relay_channel_id and adapter is not None:
        try:
            await adapter.forward_to_escalation_thread(session.relay_channel_id, label, text)
        except AdapterError as exc:
            logger.warning(_FORWARD_FAILED_EVENT, session_id=session.session_id, thread=True, error=str(exc))
    return tuple(updated)


async def _record(
    session_id: str,
    entry: RelayExchangeEntry,
    forward: Callable[[Session], Awaitable[tuple[RelayTarget, ...]]] | None,
    env: RelayEnvironment,
) -> bool:
    """Append one exchange entry under the session's relay lock, forwarding first when asked."""
    async with env.lock_for(session_id):
        current = await db.get_session(session_id)
        if current is None or current.relay_status != RelayStatus.ACTIVE:
            return False
        targets = await forward(current) if forward is not None else current.relay_targets
        await db.update_session(
            session_id,
            relay_targets=encode_relay_targets(targets),
            relay_exchange=encode_relay_exchange((*current.relay_exchange, entry)),
        )
    return True


async def divert_visitor_input(
    session: Session, text: str, actor_name: str | None, env: RelayEnvironment | None = None
) -> bool:
    """Send a visitor's message to the notified admins instead of the agent, and record it."""
    environment = env if env is not None else default_relay_environment()
    label = (actor_name or "").strip() or _VISITOR_LABEL

    async def _send(current: Session) -> tuple[RelayTarget, ...]:
        return await _forward(current, label, text, environment)

    return await _record(
        session.session_id, RelayExchangeEntry(RelayExchangeRole.VISITOR, label, text), _send, environment
    )


async def divert_visitor_file(session: Session, filename: str, env: RelayEnvironment | None = None) -> bool:
    """Tell the notified admins about a file the visitor sent, instead of handing it to the agent."""
    notice = _FILE_NOTICE_TEMPLATE.format(filename=filename)
    return await divert_visitor_input(session, notice, None, env)


# --------------------------------------------------------------------------
# Admins → visitor, and hand-back
# --------------------------------------------------------------------------


def _comparable_address(channel: str, address: str) -> str:
    """An address as both sides of a relay record it; WhatsApp numbers compare by digits."""
    if channel == MessagingChannel.WHATSAPP.value:
        return "".join(character for character in address if character.isdigit())
    return address


def _answers(target: RelayTarget, reply: AdminReply) -> bool:
    return (
        target.channel == reply.channel.value
        and _comparable_address(target.channel, target.target) == _comparable_address(reply.channel.value, reply.target)
        and reply.replied_message_id in target.message_ids
    )


def _remember_answered(key: str, env: RelayEnvironment) -> bool:
    """Record an answered reply; whether it had been answered already."""
    now = time.monotonic()
    for stale in [known for known, at in env.answered.items() if now - at > _ANSWERED_REPLY_TTL_S]:
        env.answered.pop(stale, None)
    seen = key in env.answered
    env.answered[key] = now
    return seen


def _requests_hand_back(text: str) -> bool:
    return _AGENT_TAG in text.lower()


async def _answer(session: Session, admin_name: str, text: str, env: RelayEnvironment) -> None:
    """Deliver one admin answer to the visitor and record it in the exchange."""
    name = admin_name.strip() or _ADMIN_LABEL
    entry = RelayExchangeEntry(RelayExchangeRole.ADMIN, name, text)
    if not await _record(session.session_id, entry, None, env):
        return
    try:
        await env.deliver_to_visitor(session, _ADMIN_ANSWER_TEMPLATE.format(name=name, text=text))
    except (AdapterError, RuntimeError, ValueError, OSError) as exc:
        logger.warning(_DELIVERY_FAILED_EVENT, session_id=session.session_id, error=str(exc))
        return
    logger.info(_ANSWERED_EVENT, session_id=session.session_id)


async def answer_from_admin(reply: AdminReply, text: str, env: RelayEnvironment | None = None) -> bool:
    """Take a reply to a relay message held on this computer; whether it was one.

    Tagging the agent hands the conversation back; anything else reaches the
    visitor. A reply already answered here, received again, is taken again
    without a second delivery.
    """
    environment = env if env is not None else default_relay_environment()
    for session in await db.list_relaying_sessions():
        if not any(_answers(target, reply) for target in session.relay_targets):
            continue
        key = _ANSWERED_KEY_TEMPLATE.format(channel=reply.channel.value, message_id=reply.admin_message_id)
        if _remember_answered(key, environment):
            return True
        if _requests_hand_back(text):
            await hand_back(session, environment)
        else:
            await _answer(session, reply.admin_name, text, environment)
        return True
    return False


async def answer_in_thread(
    session: Session, admin_name: str, text: str, hand_back_requested: bool, env: RelayEnvironment | None = None
) -> None:
    """Take a post in a platform desk's escalation thread: hand back, or answer the visitor."""
    environment = env if env is not None else default_relay_environment()
    if hand_back_requested:
        await hand_back(session, environment)
        return
    await _answer(session, admin_name, text, environment)


async def hand_back(session: Session, env: RelayEnvironment | None = None) -> None:
    """Return the exchange since the relay started to the same session, and end the relay."""
    environment = env if env is not None else default_relay_environment()
    async with environment.lock_for(session.session_id):
        current = await db.get_session(session.session_id)
        if current is None or current.relay_status != RelayStatus.ACTIVE:
            return
        context_block = compile_relay_context([entry.to_dict() for entry in current.relay_exchange])
        await handoff_control_payload(
            session_id=current.session_id,
            body=context_block,
            source_key=_RELAY_OCCURRENCE_TEMPLATE.format(session_id=current.session_id, nonce=uuid4().hex),
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, body=context_block),
        )
        await clear_relay(current.session_id)
        await transition_session(
            db,
            current.session_id,
            LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.HANDBACK),
        )
    event_bus.emit(
        _ESCALATION_ENDED_EVENT,  # type: ignore[arg-type]
        SessionEscalatedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )
    logger.info(_HANDED_BACK_EVENT, session_id=session.session_id, exchange=len(current.relay_exchange))


async def clear_relay(session_id: str) -> None:
    """Forget a session's relay: its status, thread, start, targets and exchange."""
    await db.update_session(session_id, relay_status=None, relay_channel_id=None, relay_started_at=None)
    await db.update_session(
        session_id, relay_targets=encode_relay_targets(()), relay_exchange=encode_relay_exchange(())
    )


# --------------------------------------------------------------------------
# Replies whose relay may live on another computer
# --------------------------------------------------------------------------


async def claim_admin_reply(
    reply: AdminReply, text: str, fleet: FleetView, env: RelayEnvironment | None = None
) -> RelayReplyDisposition:
    """Ask the live peers that run the relay whether one of them holds the relay a reply answers.

    Asked only by the computer that would otherwise route the reply, after its
    own relays did not take it. A peer that holds it takes it and answers
    ``owned``; ``none`` from every peer leaves the reply ordinary input; a peer
    that cannot answer makes the reply uncertain, and it is not routed.
    """
    environment = env if env is not None else default_relay_environment()
    peers = [member.name for member in fleet.peers if HELP_DESK_RELAY_FEATURE_ID in member.capability_set]
    if not peers:
        return RelayReplyDisposition.NOT_RELAY
    answers = await asyncio.gather(*(environment.ask_peer(peer, reply, text) for peer in peers))
    if RelayOwnerAnswer.OWNED in answers:
        logger.info(_OWNED_ELSEWHERE_EVENT, channel=reply.channel.value)
        return RelayReplyDisposition.OWNED_ELSEWHERE
    if None in answers:
        uncertain = [peer for peer, answer in zip(peers, answers, strict=True) if answer is None]
        logger.warning(_OWNER_UNCERTAIN_EVENT, channel=reply.channel.value, computers=uncertain)
        return RelayReplyDisposition.UNCERTAIN
    return RelayReplyDisposition.NOT_RELAY


async def answer_owner_query(
    arguments: list[str], caller_principal: str, env: RelayEnvironment | None = None
) -> RelayOwnerAnswer:
    """Answer a peer's ownership query: take the reply when a relay here holds it.

    Taking a reply delivers an admin's answer or hands the conversation back,
    so only a peer daemon asking under its own authority is admitted; any other
    caller is refused before anything is matched.
    """
    if caller_principal != SYSTEM_DAEMON_PRINCIPAL:
        logger.warning(_OWNER_QUERY_REFUSED_EVENT, caller=caller_principal)
        raise PermissionError(OWNER_QUERY_REFUSED)
    parsed = AdminReply.from_command_arguments(arguments)
    if parsed is None:
        return RelayOwnerAnswer.NONE
    reply, text = parsed
    return RelayOwnerAnswer.OWNED if await answer_from_admin(reply, text, env) else RelayOwnerAnswer.NONE


__all__ = [
    "ESCALATION_NOT_AVAILABLE",
    "ESCALATION_NOT_A_DESK",
    "ESCALATION_UNDELIVERED",
    "RELAY_REPLY_OWNER_COMMAND",
    "RELAY_RESEND_REPLY",
    "AdminReply",
    "EscalationRefused",
    "EscalationRequest",
    "EscalationUndelivered",
    "RelayEnvironment",
    "RelayOwnerAnswer",
    "RelayReplyDisposition",
    "answer_from_admin",
    "answer_in_thread",
    "answer_owner_query",
    "claim_admin_reply",
    "clear_relay",
    "default_relay_environment",
    "divert_visitor_file",
    "divert_visitor_input",
    "escalate",
    "hand_back",
    "is_visitor_input",
    "owning_admins",
    "platform_admin_slugs",
]
