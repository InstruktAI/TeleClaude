"""The conversation seam: every UI adapter's inbound conversation turns are decided here.

An adapter recognises and carries an entry identifier and hands each turn to
``handle_conversation_turn``; this module decides where it goes
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`),
by what the person sent and nothing else:

- a desk identifier, an invitation token's assistant, the bare entry gesture
  from a registered person, and a registered person's message with no session
  all reach an endpoint by one rule: the conversation's newest session there
  continues when open, is revived when closed, and is created when there is
  none; it then becomes the conversation's session, and the conversation's
  earlier session is left running without the conversation;
- a message without an identifier goes to the conversation's session, revived
  when it was closed;
- a conversation that carries no desk entry (Discord) never enters a desk: a
  desk identifier there is a miss, and a desk session is not its session;
- a turn on a designated channel (a shared channel the adapter provisioned for
  one registered person) enters that person's assistant only from that person,
  by the same rules as any registered person's message without an identifier;
- every miss gets the one neutral reply, at most once per cooldown window.

Only the mesh master decides, for every adapter alike: a computer that is not the
unique live master, or that finds none, ignores the turn and touches nothing. On a
per-computer adapter (Telegram) the master's own session records are the binding;
on adapters whose inbound messages reach every computer (Discord direct messages,
WhatsApp) the master's durable binding record is. Help desks run only on the master,
so every session a turn reaches runs on the computer that decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core.agent_dispatch import AgentDispatchFailure
from teleclaude.core.conversation_close import CloseOutcome
from teleclaude.core.db import ConversationBinding
from teleclaude.core.endpoints import (
    DeskIdentifier,
    Endpoint,
    InviteToken,
    assistant_endpoint,
    local_desk_endpoint,
)
from teleclaude.core.inbound.conversation_env import ConversationEnvironment, default_conversation_environment
from teleclaude.core.inbound.designated import AdoptionVerdict, assess_adoption
from teleclaude.core.inbound.fleet import FleetView, MasterResolution
from teleclaude.core.inbound.models import (
    BindOutcome,
    ConversationRef,
    ConversationTurn,
    EntryGesture,
    TurnModality,
    is_superseded,
)
from teleclaude.core.models import (
    ENDPOINT_SECTION,
    AgentDispatchMode,
    EndpointKind,
    EndpointStamp,
    EndpointStampField,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_compaction import session_compaction_owner
from teleclaude.core.session_runtime_gate import RuntimeMutationInProgress, session_runtime_owner
from teleclaude.core.session_status import is_close_started, is_session_terminal
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

NEUTRAL_REPLY = "Sorry, this conversation isn't connected to anything. If you were given a link, please open it again."
UNAVAILABLE_REPLY = "Sorry, this service is temporarily unavailable. Please try again later."
UNKNOWN_INVITE_REPLY = "I don't recognize this invite. Please contact your admin."
INVITE_CONFLICT_REPLY = "This invite is already associated with another account."
ASSISTANT_GREETING_TEMPLATE = "Hi {name}, I'm your personal assistant. What would you like to work on?"

_THINKING_MODE = "slow"
# The field of a local create answer that carries the new session id.
_CREATED_SESSION_ID_FIELD = "session_id"
# The roles whose holders are registered people, each with their own assistant.
_ASSISTANT_ROLES = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER})


class ConversationDecision(StrEnum):
    """The closed set of decisions the seam logs, one per turn outcome."""

    ENTRY_CREATED = "conversation_entry_created"
    ENTRY_CONTINUED = "conversation_entry_continued"
    ENTRY_REVIVED = "conversation_entry_revived"
    ENTRY_SUPERSEDED = "conversation_entry_superseded"
    ENTRY_REFUSED = "conversation_entry_refused"
    ENTRY_DESK_NOT_CARRIED = "conversation_entry_desk_not_carried"
    DESIGNATION_REFUSED = "conversation_designation_refused"
    ENDPOINT_ADOPTED = "conversation_endpoint_adopted"
    ADOPTION_UNRESOLVED = "conversation_adoption_unresolved"
    COMPETITOR_RETIRED = "conversation_competitor_retired"
    COMPETITOR_DEFERRED = "conversation_competitor_deferred"
    TURN_DELIVERED = "conversation_turn_delivered"
    TURN_REVIVED = "conversation_turn_revived"
    TURN_OWN_ASSISTANT = "conversation_turn_own_assistant"
    TURN_NOT_MASTER = "conversation_turn_not_master"
    TURN_UNOWNED = "conversation_turn_unowned"
    REVIVE_FAILED = "conversation_revive_failed"
    BINDING_RECORDED = "conversation_binding_recorded"
    BINDING_DROPPED = "conversation_binding_dropped"
    NEUTRAL_REPLY = "conversation_neutral_reply"
    NEUTRAL_REPLY_SUPPRESSED = "conversation_neutral_reply_suppressed"
    UNAVAILABLE_REPLY = "conversation_unavailable_reply"
    UNAVAILABLE_REPLY_SUPPRESSED = "conversation_unavailable_reply_suppressed"


class ConversationOutcome(StrEnum):
    """What became of one turn, for the adapter's own input record."""

    DELIVERED = "delivered"
    SESSION_STARTED = "session_started"
    MISSED = "missed"
    UNAVAILABLE = "unavailable"
    INVITE_REFUSED = "invite_refused"
    NOT_ROUTED_HERE = "not_routed_here"
    NO_OWNER = "no_owner"


@dataclass(frozen=True)
class _Latest:
    """The conversation's current session, which runs on this computer."""

    session: Session
    endpoint: EndpointStamp | None


@dataclass(frozen=True)
class EntryOwnership:
    """Who owns conversational entry for an origin, as this computer observed the fleet.

    ``resolution`` carries the unique live master that runs the origin, or the reason
    there is none.
    """

    resolution: MasterResolution
    host: str

    @property
    def owner(self) -> str | None:
        """The computer that owns conversational entry for the origin, when there is one."""
        master = self.resolution.master
        return master.name if master is not None else None

    @property
    def owned_here(self) -> bool:
        """Whether this computer is the owner."""
        return self.owner == self.host


def entry_ownership(fleet: FleetView, origin: InputOrigin, host: str) -> EntryOwnership:
    """Ownership of conversational entry for ``origin`` under one fleet observation."""
    return EntryOwnership(fleet.resolve_routing_master(origin), host)


async def conversation_entry_ownership(
    origin: InputOrigin, env: ConversationEnvironment | None = None
) -> EntryOwnership:
    """Whether this computer owns conversational entry for ``origin``, from the live fleet."""
    environment = env if env is not None else default_conversation_environment()
    return entry_ownership(await environment.observe_fleet(), origin, environment.host)


def _log_conversation(decision: ConversationDecision, conversation: ConversationRef, **fields: object) -> None:
    logger.info(decision, origin=conversation.origin.value, conversation=conversation.hashed_key, **fields)


def _log(decision: ConversationDecision, turn: ConversationTurn, **fields: object) -> None:
    _log_conversation(decision, turn.conversation, **fields)


def _lookup_value(key: str) -> int | str:
    """A conversation key as its sessions store it: numeric platform ids are stored as numbers."""
    return int(key) if key.isdigit() else key


def _registered_person(turn: ConversationTurn, env: ConversationEnvironment) -> str | None:
    """The sender's person slug when the sender holds the member or admin role on this computer."""
    sender = turn.sender
    if not sender.person_slug or env.effective_role(sender) not in _ASSISTANT_ROLES:
        return None
    return sender.person_slug


def _launch_intent(message: str | None) -> SessionLaunchIntent:
    if message:
        return SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            thinking_mode=_THINKING_MODE,
            message=message,
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
        )
    return SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT, thinking_mode=_THINKING_MODE, dispatch_mode=AgentDispatchMode.AUTOMATIC
    )


def _carries_content(turn: ConversationTurn) -> bool:
    """Whether the turn is a message for a session: an identifier or entry gesture is never agent input."""
    return turn.gesture is EntryGesture.NONE and bool(turn.text or turn.modality is TurnModality.MEDIA)


def _bundled_message(turn: ConversationTurn) -> str | None:
    """The turn's text when it starts a new session's launch."""
    if not _carries_content(turn) or turn.modality is not TurnModality.TEXT:
        return None
    return turn.text or None


def _is_open(session: Session) -> bool:
    return not is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at)


async def _miss(turn: ConversationTurn, env: ConversationEnvironment) -> ConversationOutcome:
    if not env.neutral_gate.admit(turn.conversation.hashed_key):
        _log(ConversationDecision.NEUTRAL_REPLY_SUPPRESSED, turn)
        return ConversationOutcome.MISSED
    _log(ConversationDecision.NEUTRAL_REPLY, turn)
    await turn.reply(NEUTRAL_REPLY)
    return ConversationOutcome.MISSED


async def _unavailable(turn: ConversationTurn, env: ConversationEnvironment) -> ConversationOutcome:
    if not env.unavailable_gate.admit(turn.conversation.hashed_key):
        _log(ConversationDecision.UNAVAILABLE_REPLY_SUPPRESSED, turn)
        return ConversationOutcome.UNAVAILABLE
    _log(ConversationDecision.UNAVAILABLE_REPLY, turn)
    await turn.reply(UNAVAILABLE_REPLY)
    return ConversationOutcome.UNAVAILABLE


# --- session creation, revival and delivery --------------------------------------------------


async def _create_at(
    turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint, message: str | None
) -> str | None:
    """Create a session at ``endpoint``; ``None`` when creation is refused or fails."""
    command = CreateSessionCommand(
        project_path=str(endpoint.folder),
        origin=turn.conversation.origin.value,
        origin_metadata=dict(turn.creation.origin_metadata),
        launch_intent=_launch_intent(message),
        initial_input=message,
        entry_point=turn.creation.entry_point,
        command_input_mode=turn.creation.command_input_mode,
        endpoint=endpoint.to_stamp(),
    )
    try:
        created = await env.create_local(command)
    except (AgentDispatchFailure, ShutdownRefusal, ValueError) as exc:
        _log(ConversationDecision.ENTRY_REFUSED, turn, endpoint=endpoint.kind.value, error=str(exc))
        return None
    session_id = created.get(_CREATED_SESSION_ID_FIELD)
    return session_id or None


async def _after_close(env: ConversationEnvironment, session: Session, *, in_flight: bool = False) -> Session:
    """The session once the runtime mutation on it has ended: a close in flight, or a revival under way.

    The idle cycle holds the runtime owner until its close ends, so waiting on the owner waits for the close.
    """
    if not in_flight and (not is_close_started(lifecycle_status=session.lifecycle_status) or session.closed_at):
        return session
    async with session_runtime_owner(session.session_id, wait=True):
        return await env.db.get_session(session.session_id) or session


async def _revive(turn: ConversationTurn, env: ConversationEnvironment, session: Session) -> Session | None:
    """Revive a closed session through the revival flow; the revived session, or ``None`` when it cannot be.

    A session whose close is in flight is revived once the close ended, so input that arrived
    during the close reaches the conversation instead of a neutral reply. A close that was
    called off leaves the session open and it continues.
    """
    session = await _after_close(env, session)
    if _is_open(session):
        return session
    try:
        revived = await env.revive_local(session.session_id)
    except RuntimeMutationInProgress:
        # Another revival of this session is under way, such as the delivery of input queued
        # across an idle close; the session is ours once it ends.
        current = await _after_close(env, session, in_flight=True)
        if _is_open(current):
            return current
        _log(ConversationDecision.REVIVE_FAILED, turn, session_id=session.session_id)
        return None
    except (AgentDispatchFailure, ShutdownRefusal, ValueError, RuntimeError) as exc:
        _log(ConversationDecision.REVIVE_FAILED, turn, session_id=session.session_id, error=str(exc))
        return None
    if not revived:
        _log(ConversationDecision.REVIVE_FAILED, turn, session_id=session.session_id)
        return None
    return await env.db.get_session(session.session_id) or session


async def _deliver(turn: ConversationTurn, session: Session) -> None:
    """Hand the turn's content to the session; an entry carries none."""
    if _carries_content(turn):
        await turn.deliver(session)
    _log(ConversationDecision.TURN_DELIVERED, turn, session_id=session.session_id)


# --- the conversation's session: the session itself (per computer) or the master's record (shared) ---


def _is_continuable_record(session: Session) -> bool:
    """Whether a retained session record may be selected to continue a conversation.

    A soft-deleted record is out of ordinary selection, and a run the system or another
    session started (a worker, a procedure or job run) is never a person's conversation.
    """
    return session.deleted_at is None and not (session.system_role or session.initiator_session_id or session.job)


def _carries_no_endpoint(conversation: ConversationRef, session: Session) -> bool:
    """Whether a session is a continuable record of the conversation that was created without an endpoint."""
    return (
        EndpointStamp.from_session(session) is None and _is_continuable_record(session) and conversation.admits(session)
    )


def _adoptable_for(
    conversation: ConversationRef, env: ConversationEnvironment, session: Session, person_slug: str
) -> bool:
    """Whether a session without an endpoint may be adopted as ``person_slug``'s assistant conversation."""
    return (
        _carries_no_endpoint(conversation, session)
        and assess_adoption(session, person_slug, env) is AdoptionVerdict.ADOPTABLE
    )


def _report_unresolved_adoption(
    conversation: ConversationRef, env: ConversationEnvironment, session: Session, person_slug: str
) -> None:
    """Report a retained record of the conversation whose recorded facts disagree with the person's assistant.

    The record is left as it is; no endpoint or participant is inferred for it.
    """
    verdict = assess_adoption(session, person_slug, env)
    if verdict is not AdoptionVerdict.ADOPTABLE:
        _log_conversation(
            ConversationDecision.ADOPTION_UNRESOLVED, conversation, session_id=session.session_id, fact=verdict.value
        )


def _can_be_conversation_session(turn: ConversationTurn, session: Session, env: ConversationEnvironment) -> bool:
    """Whether a session of the conversation's key could be its session on this computer.

    The adapter admits it and no later entry took the conversation from it; it is
    a continuable record, open or closed and carrying the endpoint it was created at. A record created without an endpoint is one too
    while it is open, or when the registered sender may adopt it as their assistant conversation.
    """
    if not _is_continuable_record(session) or not turn.conversation.admits(session) or is_superseded(session):
        return False
    stamp = EndpointStamp.from_session(session)
    if stamp is None:
        person_slug = _registered_person(turn, env)
        if person_slug is not None and _adoptable_for(turn.conversation, env, session, person_slug):
            return True
    return stamp is not None or _is_open(session)


def _is_uncarried_desk_session(turn: ConversationTurn, latest: _Latest) -> bool:
    """Whether the conversation's session is a desk session on a conversation that carries no desk entry."""
    return not turn.conversation.carries_desk_entry and latest.endpoint is not None and latest.endpoint.is_help_desk


async def _latest_per_computer(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    """The conversation's newest session that can be its session."""
    conversation = turn.conversation
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value,
        conversation.key_field,
        _lookup_value(conversation.key),
        include_closed=True,
    )
    person_slug = _registered_person(turn, env)
    for session in sessions:
        if _can_be_conversation_session(turn, session, env):
            return _Latest(session, EndpointStamp.from_session(session))
        if person_slug is not None and _carries_no_endpoint(conversation, session):
            _report_unresolved_adoption(conversation, env, session, person_slug)
    return None


async def _latest_shared(conversation: ConversationRef, env: ConversationEnvironment) -> _Latest | None:
    """The session the master's record binds the conversation to; a binding whose session is gone is dropped."""
    binding = await env.db.get_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
    if binding is None:
        return None
    session = await env.db.get_session(binding.session_id)
    if session is None or session.deleted_at is not None:
        await env.db.delete_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
        _log_conversation(ConversationDecision.BINDING_DROPPED, conversation, session_id=binding.session_id)
        return None
    return _Latest(session, binding.endpoint)


async def _latest(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    if turn.conversation.reaches_every_computer:
        return await _latest_shared(turn.conversation, env)
    return await _latest_per_computer(turn, env)


async def _newest_at(conversation: ConversationRef, env: ConversationEnvironment, endpoint: Endpoint) -> Session | None:
    """The conversation's newest session at ``endpoint``, closed ones included.

    A person's assistant endpoint is also reached by a record created without an endpoint that
    the person may adopt. Both kinds compete on creation time alone, so carrying a stamp never
    outranks being newer.
    """
    wanted = endpoint.to_stamp()
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value,
        conversation.key_field,
        _lookup_value(conversation.key),
        include_closed=True,
    )
    for session in sessions:
        stamp = EndpointStamp.from_session(session)
        if stamp is not None:
            if _is_continuable_record(session) and conversation.admits(session) and _names_same_endpoint(stamp, wanted):
                return session
            continue
        if wanted.kind is not EndpointKind.ASSISTANT or wanted.person is None:
            continue
        if _adoptable_for(conversation, env, session, wanted.person):
            return session
        if _carries_no_endpoint(conversation, session):
            _report_unresolved_adoption(conversation, env, session, wanted.person)
    return None


def _names_same_endpoint(stamp: EndpointStamp, wanted: EndpointStamp) -> bool:
    """Whether a session's stamp names the endpoint ``wanted`` names, whatever the entry history."""
    return (stamp.kind, stamp.desk_kind, stamp.slug, stamp.person) == (
        wanted.kind,
        wanted.desk_kind,
        wanted.slug,
        wanted.person,
    )


async def _supersede(conversation: ConversationRef, env: ConversationEnvironment, session_id: str) -> None:
    """Take the conversation away from an earlier session; the session itself keeps running."""
    await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: env.now_iso()})
    _log_conversation(ConversationDecision.ENTRY_SUPERSEDED, conversation, session_id=session_id)


async def _record_endpoint(
    conversation: ConversationRef, env: ConversationEnvironment, endpoint: Endpoint, session: Session
) -> Session:
    """Record ``endpoint`` on a retained session created without one; its identity and lineage are untouched.

    Adoption requests no compaction, close or extraction: the session becomes the endpoint's
    conversation and nothing else about it changes.
    """
    if EndpointStamp.from_session(session) is not None:
        return session
    await env.db.update_origin_metadata(session.session_id, ENDPOINT_SECTION, dict(endpoint.to_stamp().to_dict()))
    _log_conversation(
        ConversationDecision.ENDPOINT_ADOPTED, conversation, session_id=session.session_id, endpoint=endpoint.kind.value
    )
    return await env.db.get_session(session.session_id) or session


async def _bind_shared(
    conversation: ConversationRef,
    env: ConversationEnvironment,
    endpoint: Endpoint,
    session_id: str,
    *,
    was_superseded: bool,
) -> None:
    """Record the master's binding of a shared conversation to a session and take it from the earlier one."""
    if was_superseded:
        await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: None})
    previous = await env.db.get_conversation_binding(
        conversation.origin.value, conversation.key_field, conversation.key
    )
    await env.db.put_conversation_binding(
        ConversationBinding(
            origin=conversation.origin.value,
            key_field=conversation.key_field,
            conversation_key=conversation.key,
            session_id=session_id,
            endpoint=endpoint.to_stamp(),
            entered_at=env.now_iso(),
        )
    )
    _log_conversation(ConversationDecision.BINDING_RECORDED, conversation, session_id=session_id)
    if previous is not None and previous.session_id != session_id:
        await _supersede(conversation, env, previous.session_id)


async def _adopt(
    turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint, session_id: str, *, was_superseded: bool
) -> None:
    """Make a session the conversation's session and take the conversation from the earlier one."""
    conversation = turn.conversation
    if conversation.reaches_every_computer:
        await _bind_shared(conversation, env, endpoint, session_id, was_superseded=was_superseded)
        return
    if was_superseded:
        await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: None})
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value, conversation.key_field, _lookup_value(conversation.key), include_closed=True
    )
    for other in sessions:
        if other.session_id != session_id and _can_be_conversation_session(turn, other, env):
            await _supersede(conversation, env, other.session_id)


# --- endpoints a turn reaches ----------------------------------------------------------------


def _resolve_desk(env: ConversationEnvironment, fleet: FleetView, identifier: DeskIdentifier) -> Endpoint | None:
    """The endpoint of a desk this computer hosts, or ``None`` for a miss: desks run only on the master."""
    if not fleet.conversation_entry_safe():
        return None
    return local_desk_endpoint(identifier, env.host, env.is_master, env.roots)


def _own_assistant(env: ConversationEnvironment, person_slug: str) -> Endpoint:
    return assistant_endpoint(person_slug, env.person_workspace(person_slug), env.host)


async def _start_at(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint) -> ConversationOutcome:
    """Create a session at ``endpoint`` for the turn and make it the conversation's session."""
    session_id = await _create_at(turn, env, endpoint, _bundled_message(turn))
    if session_id is None:
        return await _miss(turn, env)
    _log(ConversationDecision.ENTRY_CREATED, turn, session_id=session_id, endpoint=endpoint.kind.value)
    await _adopt(turn, env, endpoint, session_id, was_superseded=False)
    if _carries_content(turn) and turn.modality is TurnModality.MEDIA:
        session = await env.db.get_session(session_id)
        if session is not None:
            await _deliver(turn, session)
    return ConversationOutcome.SESSION_STARTED


async def _reach(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint) -> ConversationOutcome:
    """Reach an endpoint: its newest session continues when open, is revived when closed, else one is created.

    The reached session becomes the conversation's session; when it cannot be
    revived the conversation keeps what it had.
    """
    found = await _newest_at(turn.conversation, env, endpoint)
    if found is None:
        return await _start_at(turn, env, endpoint)
    existing = await _record_endpoint(turn.conversation, env, endpoint, found)
    session = existing
    if _is_open(existing):
        _log(ConversationDecision.ENTRY_CONTINUED, turn, session_id=existing.session_id, endpoint=endpoint.kind.value)
    else:
        revived = await _revive(turn, env, existing)
        if revived is None:
            return await _miss(turn, env)
        session = revived
        _log(ConversationDecision.ENTRY_REVIVED, turn, session_id=session.session_id, endpoint=endpoint.kind.value)
    await _adopt(turn, env, endpoint, session.session_id, was_superseded=is_superseded(existing))
    if not _carries_content(turn):
        attempt = session_compaction_owner.active_attempt(session)
        if attempt is not None and not await session_compaction_owner.restore_ordinary(
            session.session_id, attempt.attempt_id
        ):
            return await _unavailable(turn, env)
        await env.db.update_session(session.session_id, last_message_sent_at=env.now_iso())
        session = await env.db.get_session(session.session_id) or session
    await _deliver(turn, session)
    return ConversationOutcome.DELIVERED


# --- decisions -------------------------------------------------------------------------------


async def _enter_by_invite(
    turn: ConversationTurn, env: ConversationEnvironment, token: InviteToken
) -> ConversationOutcome:
    person_slug = env.find_invite(token.token)
    if person_slug is None:
        await turn.reply(UNKNOWN_INVITE_REPLY)
        return ConversationOutcome.INVITE_REFUSED
    if await turn.bind_invite(person_slug) is BindOutcome.CONFLICT:
        await turn.reply(INVITE_CONFLICT_REPLY)
        return ConversationOutcome.INVITE_REFUSED
    outcome = await _reach(turn, env, _own_assistant(env, person_slug))
    if outcome is ConversationOutcome.SESSION_STARTED:
        await turn.reply(ASSISTANT_GREETING_TEMPLATE.format(name=env.display_name(person_slug)))
    return outcome


async def _adopt_retained(turn: ConversationTurn, env: ConversationEnvironment, session: Session) -> Session:
    """Adopt the conversation's session as its registered sender's assistant when it may be, else leave it."""
    person_slug = _registered_person(turn, env)
    if person_slug is None or not _adoptable_for(turn.conversation, env, session, person_slug):
        return session
    endpoint = _own_assistant(env, person_slug)
    adopted = await _record_endpoint(turn.conversation, env, endpoint, session)
    await _adopt(turn, env, endpoint, adopted.session_id, was_superseded=False)
    return adopted


async def _ordinary_turn(turn: ConversationTurn, env: ConversationEnvironment) -> ConversationOutcome:
    """A turn without an identifier: the conversation's session, else a registered person's own assistant."""
    latest = await _latest(turn, env)
    if latest is not None and _is_uncarried_desk_session(turn, latest):
        latest = None
    if latest is not None:
        session = latest.session
        if latest.endpoint is None:
            session = await _adopt_retained(turn, env, session)
        if not _is_open(session):
            revived = await _revive(turn, env, session)
            if revived is None:
                return await _miss(turn, env)
            session = revived
            _log(ConversationDecision.TURN_REVIVED, turn, session_id=session.session_id)
        await _deliver(turn, session)
        return ConversationOutcome.DELIVERED
    person_slug = _registered_person(turn, env)
    if person_slug is None:
        return await _miss(turn, env)
    outcome = await _reach(turn, env, _own_assistant(env, person_slug))
    _log(ConversationDecision.TURN_OWN_ASSISTANT, turn, outcome=outcome.value)
    return outcome


async def _designated_turn(turn: ConversationTurn, env: ConversationEnvironment) -> ConversationOutcome:
    """A turn on a designated channel: only the registered person the channel serves enters their assistant.

    A sender who resolves to another person, to no registered person, or to a person without
    an assistant gets the neutral reply, and no session is reached or created.
    """
    if _registered_person(turn, env) != turn.designated_person:
        _log(ConversationDecision.DESIGNATION_REFUSED, turn)
        return await _miss(turn, env)
    return await _ordinary_turn(turn, env)


async def _decide(turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView) -> ConversationOutcome:
    if turn.designated_person is not None:
        return await _designated_turn(turn, env)
    gesture = turn.gesture
    if gesture is EntryGesture.UNRESOLVABLE:
        return await _miss(turn, env)
    if gesture is EntryGesture.BARE:
        person_slug = _registered_person(turn, env)
        if person_slug is not None:
            return await _reach(turn, env, _own_assistant(env, person_slug))
        return await _ordinary_turn(turn, env)
    identifier = turn.identifier
    if gesture is EntryGesture.IDENTIFIER and isinstance(identifier, InviteToken):
        return await _enter_by_invite(turn, env, identifier)
    if gesture is EntryGesture.IDENTIFIER and isinstance(identifier, DeskIdentifier):
        if not turn.conversation.carries_desk_entry:
            _log(ConversationDecision.ENTRY_DESK_NOT_CARRIED, turn)
            return await _miss(turn, env)
        endpoint = _resolve_desk(env, fleet, identifier)
        if endpoint is None:
            return await _miss(turn, env)
        return await _reach(turn, env, endpoint)
    return await _ordinary_turn(turn, env)


# --- one owner per shared designated channel -----------------------------------------------------


async def _retire_competitors(
    conversation: ConversationRef, env: ConversationEnvironment, *, keep_session_id: str | None
) -> None:
    """Close this computer's open sessions of a shared designated channel other than the one that owns it.

    A session closes once its accepted work has settled, through the lifecycle's own close; one
    whose work has not settled stays open and is tried again at the channel's next use. Nothing
    is deleted or merged: a retired record keeps its identity, transcript lineage and memory provenance.
    """
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value, conversation.key_field, _lookup_value(conversation.key)
    )
    for session in sessions:
        if (
            session.session_id == keep_session_id
            or not _is_continuable_record(session)
            or not conversation.admits(session)
            or not _is_open(session)
        ):
            continue
        admission = await env.retire_session(session.session_id)
        retired = admission.outcome is CloseOutcome.CLOSED
        _log_conversation(
            ConversationDecision.COMPETITOR_RETIRED if retired else ConversationDecision.COMPETITOR_DEFERRED,
            conversation,
            session_id=session.session_id,
            reason=admission.reason.value if admission.reason is not None else admission.outcome.value,
        )


async def _bound_session_id(conversation: ConversationRef, env: ConversationEnvironment) -> str | None:
    binding = await env.db.get_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
    return binding.session_id if binding is not None else None


async def _reconcile_binding(
    conversation: ConversationRef, env: ConversationEnvironment, person_slug: str
) -> str | None:
    """Bind a shared designated channel to its newest eligible retained session; the bound session, if any.

    An existing binding wins. Adoption only records the endpoint and the binding: it revives,
    compacts and closes nothing, and it creates no session.
    """
    bound = await _latest_shared(conversation, env)
    if bound is not None:
        return bound.session.session_id
    endpoint = _own_assistant(env, person_slug)
    found = await _newest_at(conversation, env, endpoint)
    if found is None:
        return None
    adopted = await _record_endpoint(conversation, env, endpoint, found)
    await _bind_shared(conversation, env, endpoint, adopted.session_id, was_superseded=is_superseded(found))
    return adopted.session_id


async def reconcile_designated_conversation(
    conversation: ConversationRef, person_slug: str, env: ConversationEnvironment | None = None
) -> None:
    """Make a shared designated channel's retained conversation one, with this computer's competitors retired.

    On the routing master the channel's binding is settled first: an existing binding wins, else
    the newest eligible retained session is adopted and bound. Every computer then retires its
    own open sessions of the channel other than the bound one, so only the master's session
    still answers there. A master with no bound session retires nothing, since no session owns
    the channel yet. With no routing master nothing changes: the unavailable rule answers.
    """
    environment = env if env is not None else default_conversation_environment()
    fleet = await environment.observe_fleet()
    router = fleet.routing_master(conversation.origin)
    if router is None:
        return
    async with environment.locks.hold(conversation.hashed_key):
        if router.name != environment.host:
            await _retire_competitors(conversation, environment, keep_session_id=None)
            return
        bound_session_id = await _reconcile_binding(conversation, environment, person_slug)
        if bound_session_id is not None:
            await _retire_competitors(conversation, environment, keep_session_id=bound_session_id)


async def handle_conversation_turn(
    turn: ConversationTurn, env: ConversationEnvironment | None = None
) -> ConversationOutcome:
    """Decide one inbound conversation turn: enter an endpoint, reach the latest session, or miss.

    Ownership comes first, for every adapter: only the unique live master that runs the
    turn's adapter decides. Any other computer, and every computer while there is no such
    master, ignores the turn without a lookup, a session, a binding, a download or a reply.
    On a shared designated channel every non-master retires its own competing sessions, so
    the master's bound session is the only one that answers.
    """
    environment = env if env is not None else default_conversation_environment()
    conversation = turn.conversation
    fleet = await environment.observe_fleet()
    ownership = entry_ownership(fleet, conversation.origin, environment.host)
    if ownership.owner is None:
        resolution = ownership.resolution
        logger.warning(
            ConversationDecision.TURN_UNOWNED,
            origin=conversation.origin.value,
            reason=resolution.unavailability.value if resolution.unavailability is not None else None,
            computers=list(resolution.computers),
        )
        return ConversationOutcome.NO_OWNER
    designated = turn.designated_person is not None
    if not ownership.owned_here:
        logger.debug(ConversationDecision.TURN_NOT_MASTER, origin=conversation.origin.value, master=ownership.owner)
        if designated:
            async with environment.locks.hold(conversation.hashed_key):
                await _retire_competitors(conversation, environment, keep_session_id=None)
        return ConversationOutcome.NOT_ROUTED_HERE
    async with environment.locks.hold(conversation.hashed_key):
        outcome = await _decide(turn, environment, fleet)
        bound_session_id = await _bound_session_id(conversation, environment) if designated else None
        if bound_session_id is not None:
            await _retire_competitors(conversation, environment, keep_session_id=bound_session_id)
        return outcome


__all__ = [
    "ASSISTANT_GREETING_TEMPLATE",
    "INVITE_CONFLICT_REPLY",
    "NEUTRAL_REPLY",
    "UNAVAILABLE_REPLY",
    "UNKNOWN_INVITE_REPLY",
    "ConversationDecision",
    "ConversationOutcome",
    "EntryOwnership",
    "conversation_entry_ownership",
    "entry_ownership",
    "handle_conversation_turn",
    "reconcile_designated_conversation",
]
