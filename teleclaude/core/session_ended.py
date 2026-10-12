"""Session-ended reporting: every ending is stated once, as an event typed by the kind of session that ended."""

from __future__ import annotations

from datetime import UTC, datetime

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.caller_identity import (
    HUMAN_PRINCIPAL_PREFIX,
    SYSTEM_PRINCIPAL_PREFIX,
    SessionIdentityError,
    resolve_session_principal,
)
from teleclaude.core.agent_dispatch import desk_session_kind
from teleclaude.core.models import EndpointKind, EndpointStamp, Session
from teleclaude.events.envelope import EventHomeKind, EventHomeRef, EventLevel, occurrence_id
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef
from teleclaude.events.schemas.system import (
    HelpDeskSessionEnded,
    PersonSessionEnded,
    SessionEndedData,
    SessionEndedKind,
    SystemSessionEnded,
    UnknownSessionEnded,
)
from teleclaude.events.wire import LegacyFacts

logger = get_logger(__name__)

_PRODUCER = "agent_runtime"
_NOT_REPORTED_EVENT = "session_ended_not_reported"
#: What a report that cannot be published raises: the producer is unconfigured or the event is malformed
#: (RuntimeError, ValueError), or the event transport fails (Redis, socket, timeout).
_REPORT_FAILURES = (RuntimeError, ValueError, RedisError, OSError, TimeoutError)

_EVENT_BY_KIND = {
    SessionEndedKind.HELP_DESK: HelpDeskSessionEnded,
    SessionEndedKind.PERSON: PersonSessionEnded,
    SessionEndedKind.SYSTEM: SystemSessionEnded,
    SessionEndedKind.UNKNOWN: UnknownSessionEnded,
}


def _principal_of(session: Session) -> str | None:
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return None
    return principal


def session_ended_kind(session: Session) -> SessionEndedKind:
    """What kind of session the record says it was.

    A desk session is a help-desk conversation. A session the platform or another
    session started — a system principal, a starting session, or a recorded system
    role — is a session the system started, whatever human lineage it carries. Any
    other session under a human principal is that person's own conversation. A
    record that states none of these does not establish a kind.
    """
    if desk_session_kind(session.system_role, session.human_role, EndpointStamp.from_session(session)) is not None:
        return SessionEndedKind.HELP_DESK
    principal = _principal_of(session)
    started_by_system = principal is not None and principal.startswith(SYSTEM_PRINCIPAL_PREFIX)
    if started_by_system or session.initiator_session_id or session.system_role:
        return SessionEndedKind.SYSTEM
    if principal is not None and principal.startswith(HUMAN_PRINCIPAL_PREFIX):
        return SessionEndedKind.PERSON
    return SessionEndedKind.UNKNOWN


def is_conversation_session(session: Session) -> bool:
    """Whether the session is a person's conversation: a session at a desk, or a person's own session in their home.

    A system-started session (a procedure agent, a worker, an orchestrator) and a human
    session in a project or company home are not conversations.
    """
    kind = session_ended_kind(session)
    if kind is SessionEndedKind.HELP_DESK:
        return True
    if kind is not SessionEndedKind.PERSON:
        return False
    try:
        home = home_for_session_config(session.config_subject)
    except ValueError:
        return False
    return isinstance(home, EventHomeRef) and home.kind is EventHomeKind.PERSON


def is_continuing_conversation(session: Session) -> bool:
    """Whether the session is an adapter-bound conversation that a returning person continues.

    A session at a desk, or a session created at a person's assistant endpoint through conversation entry.
    Only these use the idle cycle. A person's independently started conversation is a conversation
    session without this endpoint and closes through the ordinary lifecycle.
    """
    if session_ended_kind(session) is SessionEndedKind.HELP_DESK:
        return True
    stamp = EndpointStamp.from_session(session)
    return stamp is not None and stamp.kind is EndpointKind.ASSISTANT


async def report_session_ended(session: Session) -> None:
    """Report one session's ending with its recorded home, in whatever folder it worked.

    A failure to report is logged and never fails the close that called it.
    """
    ended_at = datetime.now(UTC).isoformat()
    try:
        event_class = _EVENT_BY_KIND[session_ended_kind(session)]
        await publish_event(
            event_class(
                id=occurrence_id(session.session_id, ended_at),
                subject=SessionRef(session.session_id),
                home=home_for_session_config(session.config_subject),
                data=SessionEndedData(
                    session_id=session.session_id,
                    project_path=session.project_path,
                    ended_at=ended_at,
                ),
            ),
            LegacyFacts(producer=_PRODUCER, level=EventLevel.WORKFLOW, domain=_PRODUCER),
        )
    except _REPORT_FAILURES as exc:
        logger.warning(_NOT_REPORTED_EVENT, session_id=session.session_id, error=str(exc))
