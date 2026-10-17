"""The core-owned relay between a help-desk visitor and people in its scope."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import TypedDict
from uuid import uuid4

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.adapter_errors import AdapterError
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.identity import derive_identity_key, session_person_role
from teleclaude.core.injected_text import EnvelopeName, semantic_envelope
from teleclaude.core.models import (
    EndpointStamp,
    MessageMetadata,
    RelayExchangeEntry,
    RelayExchangeRole,
    RelayStatus,
    Session,
    encode_relay_exchange,
)
from teleclaude.core.organization import DeskScope, desk_scope
from teleclaude.core.person_messaging import (
    PersonMessageOutcome,
    send_person_message,
)
from teleclaude.core.protocols import EscalationThreadAdapter
from teleclaude.core.relay_context import compile_relay_context
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_status import SessionLifecycleStatus

logger = get_logger(__name__)

ESCALATION_NOT_A_DESK = "Escalation is a help-desk act: this session runs in no help desk"
ESCALATION_BY_ADMIN = "People in the desk's scope are the escalation target and do not escalate"
ESCALATION_ALREADY_ACTIVE = "This conversation is already escalated"
ESCALATION_SESSION_NOT_ACTIVE = "Escalation needs an active session"
ESCALATION_UNDELIVERED = "The escalation did not reach everyone in the desk's scope"
ESCALATION_THREAD_UNAVAILABLE = "The escalation did not happen: its thread could not be opened"
ESCALATION_SESSION_LINK_UNAVAILABLE = "The escalation did not happen: the visitor's session thread could not be linked"
RELAY_FORWARD_FAILED = "The escalation relay could not reach its thread"
RELAY_ANSWER_UNDELIVERED = "Your answer could not be delivered to the visitor; please resend it."
ESCALATION_HANDED_BACK_DURING_SETUP = (
    "A person handed the conversation back before every notification went out; the relay has already ended"
)
RELAY_ANSWER_AFTER_HAND_BACK = (
    "The conversation was handed back to the agent before your answer arrived; it was not delivered."
)
_AGENT_TAG = "@agent"
_ACCEPTED_STATUS = "accepted"
_HASHED_IDENTITY_LENGTH = 16
_RELAY_OCCURRENCE_TEMPLATE = "relay:{session_id}:{nonce}"
_NO_TEXT = ""

_DESK_LABEL_TEMPLATE = "the {kind}/{slug} help desk"
_UNKNOWN_ORIGIN = "unknown channel"
_UNKNOWN_IDENTITY = "unknown"
_VISITOR_LABEL = "Visitor"
_PERSON_LABEL = "Person"
_PLATFORM_LABEL = "TeleClaude"
_ESCALATION_HEADER_TEMPLATE = "Escalation from {desk}"
_ESCALATION_VISITOR_TEMPLATE = "Visitor: {name} ({origin}, {identity})"
_ESCALATION_REASON_TEMPLATE = "Reason: {reason}"
_ESCALATION_SUMMARY_TEMPLATE = "Summary: {summary}"
_SESSION_THREAD_LINK_TEMPLATE = "Customer session: {link}"
_ESCALATION_NOTIFICATION_TEMPLATE = "{desk}: {visitor} — {reason}\n{link}"
_EMAIL_SUBJECT_TEMPLATE = "Escalation for {visitor}"
_ESCALATION_SECTION_SEPARATOR = "\n"
_FILE_NOTICE_TEMPLATE = "sent a file: {filename}"
_PERSON_ANSWER_TEMPLATE = "{name}: {text}"

_RECIPIENT_FAILED_EVENT = "help_desk_escalation_recipient_failed"
_ESCALATED_LOG_EVENT = "help_desk_escalated"
_THREAD_POST_FAILED_EVENT = "help_desk_relay_thread_post_failed"
_ANSWERED_EVENT = "help_desk_relay_answered"
_HANDED_BACK_EVENT = "help_desk_relay_handed_back"
_DELIVERY_FAILED_EVENT = "help_desk_relay_visitor_delivery_failed"
_UNDELIVERED_NOTICE_FAILED_EVENT = "help_desk_relay_undelivered_notice_failed"
_ESCALATION_ROLLED_BACK_EVENT = "help_desk_escalation_rolled_back"

# Failures of one person-addressed send: unknown person, no credential, provider refusal.
_SEND_ERRORS = (ValueError, RuntimeError, OSError, httpx.HTTPError)


class EscalationOutcome(TypedDict):
    """An accepted escalation: how many people in the desk's scope were notified."""

    status: str
    notified: int
    # Set when the escalation was accepted without an outcome its desk owes.
    warning: str | None


class EscalationRefused(ValueError):
    """The session may not escalate; no person is notified and no relay starts."""


class EscalationUndelivered(ValueError):
    """The escalation did not reach its thread or every person in the desk's scope."""


class _AnswerOutcome(StrEnum):
    """What became of one answer in the escalation thread."""

    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    RELAY_ENDED = "relay_ended"


# What a person is told in the thread when their answer did not reach the visitor.
_UNANSWERED_NOTICES: dict[_AnswerOutcome, str] = {
    _AnswerOutcome.UNDELIVERED: RELAY_ANSWER_UNDELIVERED,
    _AnswerOutcome.RELAY_ENDED: RELAY_ANSWER_AFTER_HAND_BACK,
}


class RelayDeliveryFailed(RuntimeError):
    """The visitor's input could not reach the escalation thread and was not recorded."""


@dataclass(frozen=True)
class EscalationRequest:
    """What the desk agent supplies: the visitor's name, the reason and an optional summary."""

    customer_name: str
    reason: str
    summary: str = ""


SendToPerson = Callable[..., Awaitable[PersonMessageOutcome]]


@dataclass
class RelayEnvironment:
    """The identity, adapter, delivery and locking capabilities used by the relay."""

    send_to_person: SendToPerson
    desk_scope: Callable[[DeskIdentifier], DeskScope]
    thread_adapter: Callable[[], EscalationThreadAdapter | None]
    deliver_to_visitor: Callable[[Session, str], Awaitable[None]]
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def lock_for(self, session_id: str) -> asyncio.Lock:
        """The one lock that orders every write to a session's relay record."""
        return self.locks.setdefault(session_id, asyncio.Lock())


async def _send_to_visitor(session: Session, text: str) -> None:
    await get_command_service().client.send_message(
        session=session, text=text, metadata=MessageMetadata(), ephemeral=False
    )


_ENVIRONMENT_SLOT: dict[str, RelayEnvironment] = {}
_DEFAULT_ENVIRONMENT_KEY = "default"


def default_relay_environment() -> RelayEnvironment:
    """The daemon's relay environment, created once."""
    environment = _ENVIRONMENT_SLOT.get(_DEFAULT_ENVIRONMENT_KEY)
    if environment is None:
        environment = RelayEnvironment(
            send_to_person=send_person_message,
            desk_scope=desk_scope,
            thread_adapter=lambda: next(
                (
                    adapter
                    for adapter in get_command_service().client.adapters.values()
                    if isinstance(adapter, EscalationThreadAdapter)
                ),
                None,
            ),
            deliver_to_visitor=_send_to_visitor,
        )
        _ENVIRONMENT_SLOT[_DEFAULT_ENVIRONMENT_KEY] = environment
    return environment


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------


def _desk_label(stamp: EndpointStamp) -> str:
    kind = stamp.desk_kind.value if stamp.desk_kind is not None else _NO_TEXT
    return _DESK_LABEL_TEMPLATE.format(kind=kind, slug=stamp.slug or _NO_TEXT)


def _desk_identifier(stamp: EndpointStamp) -> DeskIdentifier:
    """Narrow a validated help-desk stamp to the identity owner's scope key."""
    if stamp.desk_kind is None or not stamp.slug:
        raise EscalationRefused(ESCALATION_NOT_A_DESK)
    return DeskIdentifier(stamp.desk_kind, stamp.slug)


def _visitor_origin(session: Session) -> str:
    return session.last_input_origin or _UNKNOWN_ORIGIN


def _visitor_key(session: Session) -> str | None:
    return derive_identity_key(session.origin_metadata)


def _hashed_identity(session: Session) -> str:
    key = _visitor_key(session)
    return sha256(key.encode()).hexdigest()[:_HASHED_IDENTITY_LENGTH] if key else _UNKNOWN_IDENTITY


def _escalation_text(
    session: Session, stamp: EndpointStamp, request: EscalationRequest, session_thread_link: str
) -> str:
    lines = [
        _ESCALATION_HEADER_TEMPLATE.format(desk=_desk_label(stamp)),
        _ESCALATION_VISITOR_TEMPLATE.format(
            name=request.customer_name, origin=_visitor_origin(session), identity=_hashed_identity(session)
        ),
        _ESCALATION_REASON_TEMPLATE.format(reason=request.reason),
    ]
    if request.summary.strip():
        lines.append(_ESCALATION_SUMMARY_TEMPLATE.format(summary=request.summary))
    lines.append(_SESSION_THREAD_LINK_TEMPLATE.format(link=session_thread_link))
    return _ESCALATION_SECTION_SEPARATOR.join(lines)


async def _notify(
    people: Iterable[str],
    session: Session,
    stamp: EndpointStamp,
    request: EscalationRequest,
    thread_link: str,
    env: RelayEnvironment,
) -> tuple[int, int]:
    """Notify each person in scope and return counts of people reached and failed."""

    reached = 0
    failed = 0
    for person in people:
        try:
            text = _ESCALATION_NOTIFICATION_TEMPLATE.format(
                desk=_desk_label(stamp),
                visitor=request.customer_name,
                reason=request.reason,
                link=thread_link,
            )
            await env.send_to_person(
                person,
                text,
                subject=_EMAIL_SUBJECT_TEMPLATE.format(visitor=request.customer_name),
            )
        except _SEND_ERRORS as exc:
            failed += 1
            logger.warning(_RECIPIENT_FAILED_EVENT, session_id=session.session_id, person=person, error=str(exc))
            continue
        reached += 1
    return reached, failed


async def _open_relay(session_id: str, env: RelayEnvironment) -> None:
    """Start the relay before any notification goes out: the session is escalated from here on.

    A post in the escalation thread, hand-back included, is then valid at once;
    the lifecycle owner admits a hand-back only from an escalated session.
    """
    async with env.lock_for(session_id):
        await clear_relay(session_id)
        await db.update_session(
            session_id, relay_status=RelayStatus.ACTIVE.value, relay_started_at=datetime.now(UTC).isoformat()
        )
        await transition_session(
            db, session_id, LifecycleTransition(SessionLifecycleStatus.ESCALATED, LifecycleTransitionReason.ESCALATED)
        )


async def _end_relay(session_id: str, env: RelayEnvironment) -> None:
    """Undo an escalation whose setup failed, unless a hand-back already ended it."""
    async with env.lock_for(session_id):
        current = await db.get_session(session_id)
        if current is None or current.relay_status != RelayStatus.ACTIVE:
            return
        await clear_relay(session_id)
        await transition_session(
            db, session_id, LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.HANDBACK)
        )


async def escalate(
    session: Session, request: EscalationRequest, env: RelayEnvironment | None = None
) -> EscalationOutcome:
    """Escalate a help-desk session to everyone in its desk's scope.

    Scope and the visitor's session-thread link are resolved before relay state
    changes. The thread is opened before notifications go out. Raises
    ``EscalationRefused`` for an ineligible session and
    ``EscalationUndelivered`` when the thread or any required notification fails.
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

    desk = _desk_identifier(stamp)
    people = environment.desk_scope(desk).people
    thread_adapter = environment.thread_adapter()
    if thread_adapter is None:
        raise EscalationUndelivered(ESCALATION_THREAD_UNAVAILABLE)
    try:
        session_link = await thread_adapter.session_thread_link(session)
    except AdapterError as exc:
        raise EscalationUndelivered(ESCALATION_SESSION_LINK_UNAVAILABLE) from exc

    await _open_relay(session.session_id, environment)
    try:
        brief = _escalation_text(session, stamp, request, session_link)
        try:
            thread = await thread_adapter.open_escalation_thread(desk, title=request.customer_name, brief=brief)
        except AdapterError as exc:
            raise EscalationUndelivered(ESCALATION_THREAD_UNAVAILABLE) from exc
        async with environment.lock_for(session.session_id):
            current = await db.get_session(session.session_id)
            if current is None or current.relay_status != RelayStatus.ACTIVE:
                raise EscalationUndelivered(ESCALATION_THREAD_UNAVAILABLE)
            await db.update_session(session.session_id, relay_channel_id=thread.thread_id)
        reached, failed = await _notify(people, session, stamp, request, thread.link, environment)
        if reached == 0 or failed > 0:
            raise EscalationUndelivered(ESCALATION_UNDELIVERED)
    except BaseException:
        logger.info(_ESCALATION_ROLLED_BACK_EVENT, session_id=session.session_id)
        await _end_relay(session.session_id, environment)
        raise
    registered = await db.get_session(session.session_id)
    handed_back = registered is None or registered.relay_status != RelayStatus.ACTIVE
    logger.info(
        _ESCALATED_LOG_EVENT,
        session_id=session.session_id,
        desk=_desk_label(stamp),
        notified=reached,
    )
    warning = ESCALATION_HANDED_BACK_DURING_SETUP if handed_back else None
    return EscalationOutcome(status=_ACCEPTED_STATUS, notified=reached, warning=warning)


# --------------------------------------------------------------------------
# Visitor → thread
# --------------------------------------------------------------------------


def is_visitor_input(session: Session, actor_id: str | None, caller_session_id: str | None) -> bool:
    """Whether input to a relaying session comes from its visitor, and so goes to the thread."""
    if session.relay_status != RelayStatus.ACTIVE or caller_session_id is not None or not actor_id:
        return False
    return actor_id == _visitor_key(session)


async def divert_visitor_input(
    session: Session, text: str, actor_name: str | None, env: RelayEnvironment | None = None
) -> bool:
    """Post a visitor's message in the escalation thread instead of the agent, and record it.

    Returns ``False`` when the session is no longer relaying, so the input takes
    its ordinary path. Raises ``RelayDeliveryFailed`` when the thread cannot be
    reached; nothing is recorded then.
    """
    environment = env if env is not None else default_relay_environment()
    label = (actor_name or _NO_TEXT).strip() or _VISITOR_LABEL
    async with environment.lock_for(session.session_id):
        current = await db.get_session(session.session_id)
        if current is None or current.relay_status != RelayStatus.ACTIVE:
            return False
        thread_adapter = environment.thread_adapter()
        if thread_adapter is None or current.relay_channel_id is None:
            raise RelayDeliveryFailed(RELAY_FORWARD_FAILED)
        try:
            await thread_adapter.post_to_escalation_thread(current.relay_channel_id, sender=label, text=text)
        except AdapterError as exc:
            logger.warning(_THREAD_POST_FAILED_EVENT, session_id=session.session_id, error=str(exc))
            raise RelayDeliveryFailed(RELAY_FORWARD_FAILED) from exc
        entry = RelayExchangeEntry(RelayExchangeRole.VISITOR, label, text)
        await db.update_session(
            session.session_id,
            relay_exchange=encode_relay_exchange((*current.relay_exchange, entry)),
        )
    return True


async def divert_visitor_file(session: Session, filename: str, env: RelayEnvironment | None = None) -> bool:
    """Tell the thread about a file the visitor sent, instead of handing it to the agent."""
    notice = _FILE_NOTICE_TEMPLATE.format(filename=filename)
    return await divert_visitor_input(session, notice, None, env)


# --------------------------------------------------------------------------
# People in scope → visitor, and hand-back
# --------------------------------------------------------------------------


def _requests_hand_back(text: str) -> bool:
    return _AGENT_TAG in text.lower()


async def _answer(session_id: str, person_name: str, text: str, env: RelayEnvironment) -> _AnswerOutcome:
    """Deliver one thread answer and record it under the session's relay lock."""
    name = person_name.strip() or _PERSON_LABEL
    async with env.lock_for(session_id):
        current = await db.get_session(session_id)
        if current is None or current.relay_status != RelayStatus.ACTIVE:
            return _AnswerOutcome.RELAY_ENDED
        try:
            await env.deliver_to_visitor(current, _PERSON_ANSWER_TEMPLATE.format(name=name, text=text))
        except (AdapterError, RuntimeError, ValueError, OSError) as exc:
            logger.warning(_DELIVERY_FAILED_EVENT, session_id=session_id, error=str(exc))
            return _AnswerOutcome.UNDELIVERED
        entry = RelayExchangeEntry(RelayExchangeRole.PERSON, name, text)
        await db.update_session(session_id, relay_exchange=encode_relay_exchange((*current.relay_exchange, entry)))
    logger.info(_ANSWERED_EVENT, session_id=session_id)
    return _AnswerOutcome.DELIVERED


async def _post_thread_notice(thread_id: str, notice: str, env: RelayEnvironment) -> None:
    """Post a delivery notice into the escalation thread."""
    adapter = env.thread_adapter()
    if adapter is None:
        logger.warning(_UNDELIVERED_NOTICE_FAILED_EVENT, thread_id=thread_id)
        return
    try:
        await adapter.post_to_escalation_thread(thread_id, sender=_PLATFORM_LABEL, text=notice)
    except AdapterError as exc:
        logger.warning(_UNDELIVERED_NOTICE_FAILED_EVENT, thread_id=thread_id, error=str(exc))


async def _session_for_thread(thread_id: str, env: RelayEnvironment) -> Session | None:
    """Return the active relay session currently associated with a thread."""
    for candidate in await db.list_relaying_sessions():
        if candidate.relay_channel_id != thread_id:
            continue
        async with env.lock_for(candidate.session_id):
            current = await db.get_session(candidate.session_id)
            if (
                current is not None
                and current.relay_status == RelayStatus.ACTIVE
                and current.relay_channel_id == thread_id
            ):
                return current
    return None


async def answer_in_thread(
    thread_id: str,
    name: str,
    text: str,
    mentions_agent: bool,
    env: RelayEnvironment | None = None,
) -> None:
    """Route a post in an escalation thread to its visitor or hand the relay back."""
    environment = env if env is not None else default_relay_environment()
    session = await _session_for_thread(thread_id, environment)
    if session is None:
        await _post_thread_notice(thread_id, RELAY_ANSWER_AFTER_HAND_BACK, environment)
        return
    if mentions_agent or _requests_hand_back(text):
        await hand_back(session, environment)
        return
    outcome = await _answer(session.session_id, name, text, environment)
    notice = _UNANSWERED_NOTICES.get(outcome)
    if notice is not None:
        await _post_thread_notice(thread_id, notice, environment)


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
    logger.info(_HANDED_BACK_EVENT, session_id=session.session_id, exchange=len(current.relay_exchange))


async def clear_relay(session_id: str) -> None:
    """Forget a session's relay: its status, thread, start and exchange."""
    await db.update_session(session_id, relay_status=None, relay_channel_id=None, relay_started_at=None)
    await db.update_session(session_id, relay_exchange=encode_relay_exchange(()))


# --------------------------------------------------------------------------
__all__ = [
    "ESCALATION_NOT_A_DESK",
    "ESCALATION_UNDELIVERED",
    "EscalationRefused",
    "EscalationRequest",
    "EscalationUndelivered",
    "RelayDeliveryFailed",
    "RelayEnvironment",
    "answer_in_thread",
    "clear_relay",
    "default_relay_environment",
    "divert_visitor_file",
    "divert_visitor_input",
    "escalate",
    "hand_back",
    "is_visitor_input",
]
