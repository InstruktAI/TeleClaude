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
- every miss gets the one neutral reply, at most once per cooldown window.

On a per-computer adapter (Telegram) the session is the binding and this
computer decides. On adapters whose inbound messages reach every computer
(Discord direct messages, WhatsApp) only the mesh master decides, from its
durable binding record. Help desks run only on the master, so every session a
turn reaches runs on the computer that decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER
from teleclaude.core.agent_dispatch import AgentDispatchFailure
from teleclaude.core.db import ConversationBinding
from teleclaude.core.endpoints import (
    DeskIdentifier,
    Endpoint,
    InviteToken,
    assistant_endpoint,
    local_desk_endpoint,
)
from teleclaude.core.inbound.conversation_env import ConversationEnvironment, default_conversation_environment
from teleclaude.core.inbound.fleet import FleetView
from teleclaude.core.inbound.models import BindOutcome, ConversationTurn, EntryGesture, TurnModality, is_superseded
from teleclaude.core.models import (
    ENDPOINT_SECTION,
    AgentDispatchMode,
    EndpointStamp,
    EndpointStampField,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
)
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
    ENTRY_NOT_HOSTED_HERE = "conversation_entry_not_hosted_here"
    ENTRY_REFUSED = "conversation_entry_refused"
    ENTRY_DESK_NOT_CARRIED = "conversation_entry_desk_not_carried"
    TURN_DELIVERED = "conversation_turn_delivered"
    TURN_REVIVED = "conversation_turn_revived"
    TURN_OWN_ASSISTANT = "conversation_turn_own_assistant"
    TURN_NOT_MASTER = "conversation_turn_not_master"
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


@dataclass(frozen=True)
class _Latest:
    """The conversation's current session, which runs on this computer."""

    session: Session
    endpoint: EndpointStamp | None


def _log(decision: ConversationDecision, turn: ConversationTurn, **fields: object) -> None:
    logger.info(decision, origin=turn.conversation.origin.value, conversation=turn.conversation.hashed_key, **fields)


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


def _hidden_on_this_computer(stamp: EndpointStamp | None, env: ConversationEnvironment) -> bool:
    """Whether a session's endpoint is a desk this computer does not host: desks run only on the master."""
    return stamp is not None and stamp.is_help_desk and not env.is_master


def _is_continuable_record(session: Session) -> bool:
    """Whether a retained session record may be selected to continue a conversation.

    A soft-deleted record is out of ordinary selection, and a run the system or another
    session started (a worker, a procedure or job run) is never a person's conversation.
    """
    return session.deleted_at is None and not (session.system_role or session.initiator_session_id or session.job)


def _can_be_conversation_session(turn: ConversationTurn, session: Session, env: ConversationEnvironment) -> bool:
    """Whether a session of the conversation's key could be its session on this computer.

    The adapter admits it and no later entry took the conversation from it; it is
    a continuable record, open or closed and carrying the endpoint it was created at, and it is
    not a desk this computer does not host.
    """
    if not _is_continuable_record(session) or not turn.conversation.admits(session) or is_superseded(session):
        return False
    stamp = EndpointStamp.from_session(session)
    return not _hidden_on_this_computer(stamp, env) and (stamp is not None or _is_open(session))


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
    for session in sessions:
        if _can_be_conversation_session(turn, session, env):
            return _Latest(session, EndpointStamp.from_session(session))
    return None


async def _latest_shared(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    """The session the master's record binds the conversation to; a binding whose session is gone is dropped."""
    conversation = turn.conversation
    binding = await env.db.get_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
    if binding is None:
        return None
    session = await env.db.get_session(binding.session_id)
    if session is None or session.deleted_at is not None:
        await env.db.delete_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
        _log(ConversationDecision.BINDING_DROPPED, turn, session_id=binding.session_id)
        return None
    return _Latest(session, binding.endpoint)


async def _latest(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    if turn.conversation.reaches_every_computer:
        return await _latest_shared(turn, env)
    return await _latest_per_computer(turn, env)


async def _newest_at(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint) -> Session | None:
    """The conversation's newest session at ``endpoint``, closed ones included."""
    conversation = turn.conversation
    wanted = endpoint.to_stamp()
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value,
        conversation.key_field,
        _lookup_value(conversation.key),
        include_closed=True,
    )
    for session in sessions:
        stamp = EndpointStamp.from_session(session)
        if (
            stamp is not None
            and _is_continuable_record(session)
            and conversation.admits(session)
            and _names_same_endpoint(stamp, wanted)
        ):
            return session
    return None


def _names_same_endpoint(stamp: EndpointStamp, wanted: EndpointStamp) -> bool:
    """Whether a session's stamp names the endpoint ``wanted`` names, whatever the entry history."""
    return (stamp.kind, stamp.desk_kind, stamp.slug, stamp.person) == (
        wanted.kind,
        wanted.desk_kind,
        wanted.slug,
        wanted.person,
    )


async def _supersede(turn: ConversationTurn, env: ConversationEnvironment, session_id: str) -> None:
    """Take the conversation away from an earlier session; the session itself keeps running."""
    await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: env.now_iso()})
    _log(ConversationDecision.ENTRY_SUPERSEDED, turn, session_id=session_id)


async def _adopt(
    turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint, session_id: str, *, was_superseded: bool
) -> None:
    """Make a session the conversation's session and take the conversation from the earlier one."""
    conversation = turn.conversation
    if was_superseded:
        await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: None})
    if conversation.reaches_every_computer:
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
        _log(ConversationDecision.BINDING_RECORDED, turn, session_id=session_id)
        if previous is not None and previous.session_id != session_id:
            await _supersede(turn, env, previous.session_id)
        return
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value, conversation.key_field, _lookup_value(conversation.key), include_closed=True
    )
    for other in sessions:
        if other.session_id != session_id and _can_be_conversation_session(turn, other, env):
            await _supersede(turn, env, other.session_id)


# --- endpoints a turn reaches ----------------------------------------------------------------


def _resolve_desk(
    turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView, identifier: DeskIdentifier
) -> Endpoint | None:
    """The endpoint of a desk this computer hosts, or ``None`` for a miss: desks run only on the master."""
    if not fleet.conversation_entry_safe():
        return None
    if not env.is_master:
        _log(ConversationDecision.ENTRY_NOT_HOSTED_HERE, turn)
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
    existing = await _newest_at(turn, env, endpoint)
    if existing is None:
        return await _start_at(turn, env, endpoint)
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


async def _ordinary_turn(turn: ConversationTurn, env: ConversationEnvironment) -> ConversationOutcome:
    """A turn without an identifier: the conversation's session, else a registered person's own assistant."""
    latest = await _latest(turn, env)
    if latest is not None and _is_uncarried_desk_session(turn, latest):
        latest = None
    if latest is not None:
        session = latest.session
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


async def _decide(turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView | None) -> ConversationOutcome:
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
        desk_fleet = fleet if fleet is not None else await env.observe_fleet()
        endpoint = _resolve_desk(turn, env, desk_fleet, identifier)
        if endpoint is None:
            return await _miss(turn, env)
        return await _reach(turn, env, endpoint)
    return await _ordinary_turn(turn, env)


async def handle_conversation_turn(
    turn: ConversationTurn, env: ConversationEnvironment | None = None
) -> ConversationOutcome:
    """Decide one inbound conversation turn: enter an endpoint, reach the latest session, or miss."""
    environment = env if env is not None else default_conversation_environment()
    conversation = turn.conversation
    if not conversation.reaches_every_computer:
        async with environment.locks.hold(conversation.hashed_key):
            return await _decide(turn, environment, None)
    fleet = await environment.observe_fleet()
    router = fleet.routing_master(conversation.origin)
    if router is None:
        if fleet.unavailable_replier(conversation.origin) == environment.host:
            return await _unavailable(turn, environment)
        return ConversationOutcome.NOT_ROUTED_HERE
    if router.name != environment.host:
        logger.debug(ConversationDecision.TURN_NOT_MASTER, origin=conversation.origin.value, master=router.name)
        return ConversationOutcome.NOT_ROUTED_HERE
    async with environment.locks.hold(conversation.hashed_key):
        return await _decide(turn, environment, fleet)


__all__ = [
    "ASSISTANT_GREETING_TEMPLATE",
    "INVITE_CONFLICT_REPLY",
    "NEUTRAL_REPLY",
    "UNAVAILABLE_REPLY",
    "UNKNOWN_INVITE_REPLY",
    "ConversationDecision",
    "ConversationOutcome",
    "handle_conversation_turn",
]
