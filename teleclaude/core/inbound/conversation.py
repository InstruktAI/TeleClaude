"""The conversation seam: every UI adapter's inbound conversation turns are decided here.

An adapter recognises and carries an entry identifier and hands each turn to
``handle_conversation_turn``; this module decides where it goes
(`projects/teleclaude/spec/feature/agent_runtime/conversation-entry`):

- an entry creates a session at the resolved endpoint and then supersedes
  the conversation's earlier binding: a superseded desk session ends, a
  superseded assistant keeps running without the conversation;
- an ordinary message goes to the conversation's latest session; a returning
  customer whose desk session closed starts a new one at that desk; with no
  session, registered people route by role;
- every miss gets the one neutral reply, at most once per cooldown window.

On a per-computer adapter (Telegram) the session is the binding and this
computer decides. On adapters whose inbound messages reach every computer
(Discord direct messages, WhatsApp) only the mesh master decides, from its
durable binding record; it creates and reaches sessions on their hosts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    HUMAN_ROLE_CONTRIBUTOR,
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLE_MEMBER,
    HUMAN_ROLE_NEWCOMER,
)
from teleclaude.core.agent_dispatch import AgentDispatchFailure
from teleclaude.core.command_dispatch import RelayFailure, RemoteDispatchError, RemoteDispatchReason
from teleclaude.core.db import ConversationBinding, ConversationBindingOrphan
from teleclaude.core.endpoints import (
    DeskIdentifier,
    Endpoint,
    InviteToken,
    assistant_endpoint,
    local_desk_endpoint,
    platform_desk_endpoint,
    resolve_host,
    stamp_desk_identifier,
)
from teleclaude.core.help_desk_relay import (
    RELAY_RESEND_REPLY,
    RelayReplyDisposition,
    answer_from_admin,
    claim_admin_reply,
)
from teleclaude.core.inbound.adoption import is_superseded
from teleclaude.core.inbound.conversation_env import ConversationEnvironment, default_conversation_environment
from teleclaude.core.inbound.cutover import (
    SharedRoutingState,
    await_routing_start,
    changeover_exports_outstanding,
    shared_routing_state,
)
from teleclaude.core.inbound.fleet import FleetView
from teleclaude.core.inbound.models import BindOutcome, ConversationTurn, EntryGesture, TurnModality
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
from teleclaude.core.session_status import is_session_terminal
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand

logger = get_logger(__name__)

NEUTRAL_REPLY = "Sorry, this conversation isn't connected to anything. If you were given a link, please open it again."
UNAVAILABLE_REPLY = "Sorry, this service is temporarily unavailable. Please try again later."
UNKNOWN_INVITE_REPLY = "I don't recognize this invite. Please contact your admin."
INVITE_CONFLICT_REPLY = "This invite is already associated with another account."
ASSISTANT_GREETING_TEMPLATE = "Hi {name}, I'm your personal assistant. What would you like to work on?"

_THINKING_MODE = "slow"
_REMOTE_PROJECT_PATH = ""
# The field of a local create answer that carries the new session id.
_CREATED_SESSION_ID_FIELD = "session_id"
_ASSISTANT_ROLES = frozenset({HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER})
_PLATFORM_DESK_ROLES = frozenset({HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER})


class ConversationDecision(StrEnum):
    """The closed set of decisions the seam logs, one per turn outcome."""

    ENTRY_CREATED = "conversation_entry_created"
    ENTRY_SUPERSEDED = "conversation_entry_superseded"
    ENTRY_NOT_HOSTED_HERE = "conversation_entry_not_hosted_here"
    ENTRY_REFUSED = "conversation_entry_refused"
    TURN_DELIVERED = "conversation_turn_delivered"
    TURN_RETURNING_CUSTOMER = "conversation_turn_returning_customer"
    TURN_ROLE_FALLBACK = "conversation_turn_role_fallback"
    TURN_FALLBACK_HELD = "conversation_turn_fallback_held_for_changeover"
    TURN_NOT_MASTER = "conversation_turn_not_master"
    BINDING_RECORDED = "conversation_binding_recorded"
    REMOTE_CREATE_FAILED = "conversation_remote_create_failed"
    REMOTE_DELIVER_FAILED = "conversation_remote_deliver_failed"
    NEUTRAL_REPLY = "conversation_neutral_reply"
    NEUTRAL_REPLY_SUPPRESSED = "conversation_neutral_reply_suppressed"
    UNAVAILABLE_REPLY = "conversation_unavailable_reply"
    UNAVAILABLE_REPLY_SUPPRESSED = "conversation_unavailable_reply_suppressed"
    RELAY_ANSWERED = "conversation_relay_answered"


class ConversationOutcome(StrEnum):
    """What became of one turn, for the adapter's own input record."""

    DELIVERED = "delivered"
    SESSION_STARTED = "session_started"
    MISSED = "missed"
    UNAVAILABLE = "unavailable"
    INVITE_REFUSED = "invite_refused"
    NOT_ROUTED_HERE = "not_routed_here"
    # Master routing is not active here yet: the adapter handles the turn as before the cutover.
    BEFORE_CUTOVER = "before_cutover"
    # The message answered an escalation relay, here or on the computer that holds it.
    RELAY_ANSWERED = "relay_answered"
    # The message may answer a relay whose holder could not be asked; the sender is asked to resend.
    RELAY_REPLY_UNMATCHED = "relay_reply_unmatched"


@dataclass(frozen=True)
class _Latest:
    """The conversation's current binding: its latest session and where it runs."""

    session_id: str
    host: str
    endpoint: EndpointStamp | None
    # The session when it runs on this computer; ``None`` for a remote one.
    session: Session | None = None

    @property
    def is_local_open(self) -> bool:
        session = self.session
        return session is not None and not is_session_terminal(
            lifecycle_status=session.lifecycle_status, closed_at=session.closed_at
        )


def _log(decision: ConversationDecision, turn: ConversationTurn, **fields: object) -> None:
    logger.info(decision, origin=turn.conversation.origin.value, conversation=turn.conversation.hashed_key, **fields)


def _lookup_value(key: str) -> int | str:
    """A conversation key as its sessions store it: numeric platform ids are stored as numbers."""
    return int(key) if key.isdigit() else key


def _sender_role(turn: ConversationTurn) -> str:
    sender = turn.sender
    if not sender.person_slug:
        return HUMAN_ROLE_CUSTOMER
    return sender.person_role or HUMAN_ROLE_CUSTOMER


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


def _bundled_message(turn: ConversationTurn) -> str | None:
    """The turn's text when it starts a new session's launch; an identifier is never agent input."""
    if turn.gesture is not EntryGesture.NONE or turn.modality is not TurnModality.TEXT:
        return None
    return turn.text or None


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


# --- session creation, delivery and closing -------------------------------------------------


async def _create_at(
    turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint, message: str | None
) -> str | None:
    """Create a session at ``endpoint``; ``None`` when creation is refused, fails or times out."""
    is_local = endpoint.host == env.host
    command = CreateSessionCommand(
        project_path=str(endpoint.folder) if endpoint.folder is not None else _REMOTE_PROJECT_PATH,
        origin=turn.conversation.origin.value,
        origin_metadata=dict(turn.creation.origin_metadata),
        launch_intent=_launch_intent(message),
        initial_input=message,
        entry_point=turn.creation.entry_point,
        command_input_mode=turn.creation.command_input_mode,
        endpoint=endpoint.to_stamp(),
    )
    if is_local:
        try:
            created = await env.create_local(command)
        except (AgentDispatchFailure, ValueError) as exc:
            _log(ConversationDecision.ENTRY_REFUSED, turn, endpoint=endpoint.kind.value, error=str(exc))
            return None
        session_id = created.get(_CREATED_SESSION_ID_FIELD)
        return session_id or None
    # The master chooses the id, so a create whose answer is lost is still known by it.
    session_id = str(uuid.uuid4())
    command.session_id = session_id
    command.computer = endpoint.host
    try:
        await env.dispatch(command)
    except RelayFailure as exc:
        if exc.reason is RemoteDispatchReason.UNREACHABLE:
            await env.db.record_conversation_binding_orphan(
                ConversationBindingOrphan(session_id=session_id, host=endpoint.host, recorded_at=env.now_iso())
            )
        _log(ConversationDecision.REMOTE_CREATE_FAILED, turn, host=endpoint.host, reason=exc.reason.value)
        return None
    except (RemoteDispatchError, AgentDispatchFailure) as exc:
        _log(ConversationDecision.REMOTE_CREATE_FAILED, turn, host=endpoint.host, error=str(exc))
        return None
    return session_id


async def _close(env: ConversationEnvironment, session_id: str, host: str) -> None:
    """End a session through the ordinary close path: here, or by its host."""
    if host == env.host:
        await env.close_local(session_id)
        return
    command = CloseSessionCommand(session_id=session_id)
    command.computer = host
    await env.dispatch(command)


async def _stamp_superseded(env: ConversationEnvironment, session_id: str) -> None:
    await env.db.update_origin_metadata(session_id, ENDPOINT_SECTION, {EndpointStampField.SUPERSEDED_AT: env.now_iso()})


async def _supersede(
    turn: ConversationTurn, env: ConversationEnvironment, session_id: str, host: str, endpoint: EndpointStamp | None
) -> None:
    """Take the conversation away from an earlier session: a desk session ends, an assistant keeps running."""
    if host == env.host:
        await _stamp_superseded(env, session_id)
    if endpoint is not None and endpoint.is_help_desk:
        await _close(env, session_id, host)
    _log(ConversationDecision.ENTRY_SUPERSEDED, turn, session_id=session_id, host=host)


async def _deliver(turn: ConversationTurn, env: ConversationEnvironment, latest: _Latest) -> bool:
    """Hand the turn to the latest session; whether it reached it."""
    has_content = bool(turn.text) or turn.modality is TurnModality.MEDIA
    if latest.session is not None:
        if has_content:
            await turn.deliver(latest.session)
        _log(ConversationDecision.TURN_DELIVERED, turn, session_id=latest.session_id)
        return True
    command = turn.remote_command(latest.session_id) if has_content else None
    if command is not None:
        command.computer = latest.host
        try:
            await env.dispatch(command)
        except (RemoteDispatchError, AgentDispatchFailure) as exc:
            _log(ConversationDecision.REMOTE_DELIVER_FAILED, turn, host=latest.host, error=str(exc))
            return False
    _log(ConversationDecision.TURN_DELIVERED, turn, session_id=latest.session_id, host=latest.host)
    return True


# --- the binding: the session itself (per computer) or the master's record (shared) --------


async def _latest_per_computer(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    conversation = turn.conversation
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value,
        conversation.key_field,
        _lookup_value(conversation.key),
        include_closed=_sender_role(turn) == HUMAN_ROLE_CUSTOMER,
    )
    for session in sessions:
        if conversation.admits(session) and not is_superseded(session):
            return _Latest(session.session_id, env.host, EndpointStamp.from_session(session), session)
    return None


async def _latest_shared(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    conversation = turn.conversation
    binding = await env.db.get_conversation_binding(conversation.origin.value, conversation.key_field, conversation.key)
    if binding is None:
        return None
    session = await env.db.get_session(binding.session_id) if binding.host == env.host else None
    if binding.host == env.host and session is None:
        return _Latest(binding.session_id, binding.host, binding.endpoint)
    return _Latest(binding.session_id, binding.host, binding.endpoint, session)


async def _latest(turn: ConversationTurn, env: ConversationEnvironment) -> _Latest | None:
    if turn.conversation.reaches_every_computer:
        return await _latest_shared(turn, env)
    return await _latest_per_computer(turn, env)


async def _bind(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint, session_id: str) -> None:
    """Record the new binding where the authority keeps it, then supersede the earlier one."""
    conversation = turn.conversation
    if conversation.reaches_every_computer:
        previous = await env.db.get_conversation_binding(
            conversation.origin.value, conversation.key_field, conversation.key
        )
        await env.db.put_conversation_binding(
            ConversationBinding(
                origin=conversation.origin.value,
                key_field=conversation.key_field,
                conversation_key=conversation.key,
                host=endpoint.host,
                session_id=session_id,
                endpoint=endpoint.to_stamp(),
                entered_at=env.now_iso(),
            )
        )
        _log(ConversationDecision.BINDING_RECORDED, turn, session_id=session_id, host=endpoint.host)
        if previous is not None and previous.session_id != session_id:
            await _supersede(turn, env, previous.session_id, previous.host, previous.endpoint)
        return
    sessions = await env.db.get_sessions_by_origin_metadata(
        conversation.origin.value, conversation.key_field, _lookup_value(conversation.key)
    )
    for session in sessions:
        if session.session_id != session_id and conversation.admits(session) and not is_superseded(session):
            await _supersede(turn, env, session.session_id, env.host, EndpointStamp.from_session(session))


# --- endpoints a turn reaches -----------------------------------------------------------------


def _desk_on(env: ConversationEnvironment, identifier: DeskIdentifier, host: str) -> Endpoint | None:
    """The desk's endpoint on ``host``: resolved from this computer's own declarations when local."""
    if host == env.host:
        return local_desk_endpoint(identifier, env.host, env.roots)
    return Endpoint(kind=EndpointKind.HELP_DESK, host=host, desk_kind=identifier.kind, slug=identifier.slug)


def _resolve_desk(
    turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView, identifier: DeskIdentifier
) -> Endpoint | None:
    """The hosting endpoint of a desk this conversation may reach, or ``None`` for a miss."""
    if not fleet.conversation_entry_safe():
        return None
    host = resolve_host(identifier, fleet.desk_announcements())
    if host is None:
        return None
    if host != env.host and not turn.conversation.reaches_every_computer:
        _log(ConversationDecision.ENTRY_NOT_HOSTED_HERE, turn, host=host)
        return None
    return _desk_on(env, identifier, host)


def _own_assistant(env: ConversationEnvironment, person_slug: str) -> Endpoint:
    return assistant_endpoint(person_slug, env.person_workspace(person_slug), env.host)


def _role_endpoint(turn: ConversationTurn, env: ConversationEnvironment) -> Endpoint | None:
    """Where a conversation with no open session goes by its sender's role."""
    role = _sender_role(turn)
    if role in _ASSISTANT_ROLES and turn.sender.person_slug:
        return _own_assistant(env, turn.sender.person_slug)
    if role in _PLATFORM_DESK_ROLES:
        return platform_desk_endpoint(env.host, env.roots)
    return None


# --- decisions ---------------------------------------------------------------------------------


async def _enter(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint) -> ConversationOutcome:
    session_id = await _create_at(turn, env, endpoint, None)
    if session_id is None:
        return await _miss(turn, env)
    _log(
        ConversationDecision.ENTRY_CREATED,
        turn,
        session_id=session_id,
        host=endpoint.host,
        endpoint=endpoint.kind.value,
    )
    await _bind(turn, env, endpoint, session_id)
    return ConversationOutcome.SESSION_STARTED


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
    outcome = await _enter(turn, env, _own_assistant(env, person_slug))
    if outcome is ConversationOutcome.SESSION_STARTED:
        await turn.reply(ASSISTANT_GREETING_TEMPLATE.format(name=env.display_name(person_slug)))
    return outcome


async def _start_at(turn: ConversationTurn, env: ConversationEnvironment, endpoint: Endpoint) -> ConversationOutcome:
    """Start a session for an ordinary turn that has nowhere open to go, and bind it."""
    session_id = await _create_at(turn, env, endpoint, _bundled_message(turn))
    if session_id is None:
        return await _miss(turn, env)
    await _bind(turn, env, endpoint, session_id)
    if turn.modality is TurnModality.MEDIA:
        latest = await _latest(turn, env)
        if latest is not None:
            await _deliver(turn, env, latest)
    return ConversationOutcome.SESSION_STARTED


async def _is_open_remotely(turn: ConversationTurn, env: ConversationEnvironment, latest: _Latest) -> bool | None:
    """Whether the bound remote session is still open, from its host's own records; ``None`` if it cannot say."""
    exported = await env.export_from(latest.host, turn.conversation)
    if exported is None:
        return None
    return any(item.session_id == latest.session_id for item in exported)


def _returning_customer_desk(
    turn: ConversationTurn, env: ConversationEnvironment, latest: _Latest, fleet: FleetView | None
) -> Endpoint | None:
    """The desk a customer whose desk session closed returns to, while that desk is still enabled."""
    if _sender_role(turn) != HUMAN_ROLE_CUSTOMER or latest.endpoint is None:
        return None
    identifier = stamp_desk_identifier(latest.endpoint)
    if identifier is None:
        return None
    if not turn.conversation.reaches_every_computer:
        return local_desk_endpoint(identifier, env.host, env.roots)
    if fleet is None:
        return None
    return _resolve_desk(turn, env, fleet, identifier)


async def _ordinary_turn(
    turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView | None
) -> ConversationOutcome:
    latest = await _latest(turn, env)
    if latest is not None:
        if latest.is_local_open:
            await _deliver(turn, env, latest)
            return ConversationOutcome.DELIVERED
        if latest.session is None and latest.host != env.host:
            if await _deliver(turn, env, latest):
                return ConversationOutcome.DELIVERED
            if await _is_open_remotely(turn, env, latest) is not False:
                return await _unavailable(turn, env)
        desk = _returning_customer_desk(turn, env, latest, fleet)
        if desk is not None:
            outcome = await _start_at(turn, env, desk)
            if outcome is ConversationOutcome.SESSION_STARTED:
                _log(ConversationDecision.TURN_RETURNING_CUSTOMER, turn, host=desk.host)
            return outcome
    endpoint = _role_endpoint(turn, env)
    if endpoint is None:
        return await _miss(turn, env)
    if turn.conversation.reaches_every_computer:
        outstanding = await changeover_exports_outstanding(env)
        if outstanding:
            # The conversation may be open on a computer whose sessions are not bound yet.
            _log(ConversationDecision.TURN_FALLBACK_HELD, turn, computers=outstanding)
            return await _unavailable(turn, env)
    outcome = await _start_at(turn, env, endpoint)
    if outcome is ConversationOutcome.SESSION_STARTED:
        _log(ConversationDecision.TURN_ROLE_FALLBACK, turn, role=_sender_role(turn), endpoint=endpoint.kind.value)
    return outcome


async def _decide(turn: ConversationTurn, env: ConversationEnvironment, fleet: FleetView | None) -> ConversationOutcome:
    gesture = turn.gesture
    if gesture is EntryGesture.UNRESOLVABLE:
        return await _miss(turn, env)
    if gesture is EntryGesture.BARE:
        if _sender_role(turn) in _ASSISTANT_ROLES and turn.sender.person_slug:
            return await _enter(turn, env, _own_assistant(env, turn.sender.person_slug))
        return await _ordinary_turn(turn, env, fleet)
    identifier = turn.identifier
    if gesture is EntryGesture.IDENTIFIER and isinstance(identifier, InviteToken):
        return await _enter_by_invite(turn, env, identifier)
    if gesture is EntryGesture.IDENTIFIER and isinstance(identifier, DeskIdentifier):
        desk_fleet = fleet if fleet is not None else await env.observe_fleet()
        endpoint = _resolve_desk(turn, env, desk_fleet, identifier)
        if endpoint is None:
            return await _miss(turn, env)
        return await _enter(turn, env, endpoint)
    return await _ordinary_turn(turn, env, fleet)


async def _held_relay_reply(turn: ConversationTurn, fleet: FleetView) -> ConversationOutcome | None:
    """On the computer about to route a reply this computer's relays did not take: ask the fleet first.

    ``None`` leaves the turn ordinary input.
    """
    if turn.relay_reply is None:
        return None
    disposition = await claim_admin_reply(turn.relay_reply, turn.text, fleet)
    if disposition is RelayReplyDisposition.OWNED_ELSEWHERE:
        return ConversationOutcome.RELAY_ANSWERED
    if disposition is RelayReplyDisposition.UNCERTAIN:
        await turn.reply(RELAY_RESEND_REPLY)
        return ConversationOutcome.RELAY_REPLY_UNMATCHED
    return None


async def handle_conversation_turn(
    turn: ConversationTurn, env: ConversationEnvironment | None = None
) -> ConversationOutcome:
    """Decide one inbound conversation turn: enter an endpoint, reach the latest session, or miss."""
    environment = env if env is not None else default_conversation_environment()
    conversation = turn.conversation
    if turn.relay_reply is not None and await answer_from_admin(turn.relay_reply, turn.text):
        _log(ConversationDecision.RELAY_ANSWERED, turn)
        return ConversationOutcome.RELAY_ANSWERED
    if not conversation.reaches_every_computer:
        async with environment.locks.hold(conversation.hashed_key):
            return await _decide(turn, environment, None)
    fleet = await environment.observe_fleet()
    # Admitted before the state is read and held through any handling on its own, so an armed
    # computer announces only once nothing it handled on its own is still running.
    async with environment.legacy.admit():
        state = await shared_routing_state(environment, fleet)
        if state is SharedRoutingState.BEFORE_CUTOVER:
            held = await _held_relay_reply(turn, fleet)
            if held is not None:
                return held
            if turn.before_cutover is not None:
                await turn.before_cutover()
            return ConversationOutcome.BEFORE_CUTOVER
    if state is SharedRoutingState.UNKNOWN:
        if fleet.unavailable_replier(conversation.origin) == environment.host:
            return await _unavailable(turn, environment)
        return ConversationOutcome.NOT_ROUTED_HERE
    router = fleet.routing_master(conversation.origin)
    if router is None:
        if fleet.unavailable_replier(conversation.origin) == environment.host:
            return await _unavailable(turn, environment)
        return ConversationOutcome.NOT_ROUTED_HERE
    if router.name != environment.host:
        logger.debug(ConversationDecision.TURN_NOT_MASTER, origin=conversation.origin.value, master=router.name)
        return ConversationOutcome.NOT_ROUTED_HERE
    held = await _held_relay_reply(turn, fleet)
    if held is not None:
        return held
    if state is SharedRoutingState.CHANGING_OVER and not await await_routing_start(environment):
        return await _unavailable(turn, environment)
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
