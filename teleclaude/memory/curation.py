"""Memory curation: the operations a memory agent uses to keep one person's memories current.

Every operation names a conversation session, and memory derives the scope from that
session's record: the person's identity key, the memory namespace, and what a record
about the person is about. The agent never supplies an identity key, so a run cannot
write outside the one person and namespace it was handed. Memory applies the changes
it is asked for and decides nothing about content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.identity import MemoryPerson, memory_person_for_session
from teleclaude.core.models import EndpointStamp, HelpDeskKind, Session
from teleclaude.core.session_ended import is_conversation_session
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.memory.store import MemoryStore, auto_title, resolve_observation_project_scope
from teleclaude.memory.types import MemoryState, ObservationInput, ObservationResult, ObservationType

logger = get_logger(__name__)

_MEMORY_ADDED_EVENT = "memory_curation_added"
_MEMORY_UPDATED_EVENT = "memory_curation_updated"
_MEMORY_RETIRED_EVENT = "memory_curation_retired"
_PROSPECT_RECORDED_EVENT = "memory_curation_prospect_recorded"
_READ_POINT_ADVANCED_EVENT = "memory_curation_read_point_advanced"

_REFUSAL_SESSION_NOT_FOUND = "Session {session_id} was not found."
_REFUSAL_NOT_A_CONVERSATION = (
    "Session {session_id} is not a conversation session. Memories are curated for a desk session "
    "and for a person's own session in their home."
)
_REFUSAL_NO_PERSON = "Session {session_id} names no person whose memories could be kept."
_REFUSAL_NOT_A_DESK = (
    "Session {session_id} is not a help-desk conversation, so it has no desk home to collect prospects for."
)
_REFUSAL_OUT_OF_SCOPE = (
    "Memory {observation_id} is not a current memory of the person in session {session_id}'s scope. "
    "List the scope with `telec memories scope --session {session_id}`."
)


class CurationRefusalReason(StrEnum):
    """Why a curation operation changed nothing."""

    SESSION_NOT_FOUND = "session_not_found"
    NOT_A_CONVERSATION = "not_a_conversation"
    NO_PERSON = "no_person"
    NOT_A_DESK = "not_a_desk"
    OUT_OF_SCOPE = "out_of_scope"


_REFUSAL_MESSAGES: dict[CurationRefusalReason, str] = {
    CurationRefusalReason.SESSION_NOT_FOUND: _REFUSAL_SESSION_NOT_FOUND,
    CurationRefusalReason.NOT_A_CONVERSATION: _REFUSAL_NOT_A_CONVERSATION,
    CurationRefusalReason.NO_PERSON: _REFUSAL_NO_PERSON,
    CurationRefusalReason.NOT_A_DESK: _REFUSAL_NOT_A_DESK,
    CurationRefusalReason.OUT_OF_SCOPE: _REFUSAL_OUT_OF_SCOPE,
}
_NOT_FOUND_STATUS = 404
_REFUSED_STATUS = 409


class CurationRefusedError(RuntimeError):
    """A curation operation was refused and changed nothing."""

    def __init__(self, reason: CurationRefusalReason, *, session_id: str, observation_id: int | None = None) -> None:
        self.reason = reason
        super().__init__(
            _REFUSAL_MESSAGES[reason].format(session_id=session_id, observation_id=observation_id),
        )

    @property
    def http_status_code(self) -> int:
        """The HTTP status that reports this refusal."""
        return _NOT_FOUND_STATUS if self.reason is CurationRefusalReason.SESSION_NOT_FOUND else _REFUSED_STATUS


@dataclass(frozen=True)
class DeskHome:
    """The home that owns a desk, as prospects are recorded for it."""

    namespace: str
    subject: str
    subject_owner: str


@dataclass(frozen=True)
class MemoryScope:
    """One person in one memory namespace, as a conversation session defines it."""

    session_id: str
    namespace: str
    person: MemoryPerson
    subject: str
    subject_owner: str
    desk_home: DeskHome | None
    read_point: datetime | None

    @property
    def is_desk(self) -> bool:
        """Whether the session is a help-desk conversation."""
        return self.desk_home is not None


def _desk_home(stamp: EndpointStamp) -> DeskHome | None:
    """The home a desk stamp names, or ``None`` when the stamp does not name one."""
    if stamp.desk_kind is None or stamp.slug is None:
        return None
    if stamp.desk_kind is HelpDeskKind.COMPANY:
        subject = SubjectRef(ConfigSubjectKind.COMPANY, stamp.slug).to_token()
        return DeskHome(stamp.slug, subject, EventHomeOwnerMarker.NONE.value)
    subject, owner = resolve_observation_project_scope(stamp.slug)
    return DeskHome(stamp.slug, subject, owner)


def _working_folder_name(session: Session) -> str | None:
    if not session.project_path:
        return None
    folder = Path(session.project_path) / session.subdir if session.subdir else Path(session.project_path)
    return folder.name


def memory_scope(session: Session) -> MemoryScope | None:
    """The one derivation of a session's memory scope; ``None`` when the session names no person or namespace.

    The namespace is the desk's identifier for a session at a help desk (every desk folder
    carries the same name, so the folder cannot tell desks apart), otherwise the working
    folder's name. A registered person's memories are about that person. An unregistered
    visitor's are about the desk's home, recorded under their own platform identity.
    """
    person = memory_person_for_session(session)
    if person is None:
        return None
    stamp = EndpointStamp.from_session(session)
    desk_home = _desk_home(stamp) if stamp is not None and stamp.is_help_desk else None
    if desk_home is not None and stamp is not None and stamp.desk_kind is not None and stamp.slug is not None:
        namespace: str | None = DeskIdentifier(stamp.desk_kind, stamp.slug).render()
    else:
        namespace = _working_folder_name(session)
    if namespace is None:
        return None
    if person.person_slug is not None:
        subject = SubjectRef(ConfigSubjectKind.PERSON, person.person_slug).to_token()
        subject_owner = EventHomeOwnerMarker.NONE.value
    elif desk_home is not None:
        subject, subject_owner = desk_home.subject, desk_home.subject_owner
    else:
        subject, subject_owner = EventHomeMarker.UNKNOWN.value, EventHomeOwnerMarker.UNRESOLVED.value
    return MemoryScope(
        session_id=session.session_id,
        namespace=namespace,
        person=person,
        subject=subject,
        subject_owner=subject_owner,
        desk_home=desk_home,
        read_point=session.last_memory_extraction_at or session.created_at,
    )


async def _scope_of(session_id: str) -> MemoryScope:
    """The scope of a conversation session, or the refusal that names why it has none."""
    session = await db.get_session(session_id)
    if session is None:
        raise CurationRefusedError(CurationRefusalReason.SESSION_NOT_FOUND, session_id=session_id)
    if not is_conversation_session(session):
        raise CurationRefusedError(CurationRefusalReason.NOT_A_CONVERSATION, session_id=session_id)
    scope = memory_scope(session)
    if scope is None:
        raise CurationRefusedError(CurationRefusalReason.NO_PERSON, session_id=session_id)
    return scope


@dataclass(frozen=True)
class ScopeListing:
    """A scope with the current memories in it and, for a desk conversation, the prospects it already yielded."""

    scope: MemoryScope
    memories: list[db_models.MemoryObservation]
    prospects: list[db_models.MemoryObservation]


async def list_scope(session_id: str) -> ScopeListing:
    """List the scope a conversation session defines: its current memories and its recorded prospects."""
    scope = await _scope_of(session_id)
    memories_statement = (
        select(db_models.MemoryObservation)
        .where(db_models.MemoryObservation.project == scope.namespace)
        .where(db_models.MemoryObservation.identity_key == scope.person.identity_key)
        .where(db_models.MemoryObservation.state == MemoryState.CURRENT.value)
        .order_by(db_models.MemoryObservation.id)  # type: ignore[arg-type]
    )
    prospects_statement = (
        select(db_models.MemoryObservation)
        .where(db_models.MemoryObservation.source_session_id == session_id)
        .where(db_models.MemoryObservation.state == MemoryState.PROSPECT.value)
        .order_by(db_models.MemoryObservation.id)  # type: ignore[arg-type]
    )
    async with db._session() as session:
        memories = list((await session.exec(memories_statement)).all())
        prospects = list((await session.exec(prospects_statement)).all()) if scope.is_desk else []
    return ScopeListing(scope=scope, memories=memories, prospects=prospects)


async def add_memory(session_id: str, observation_type: ObservationType, text: str) -> ObservationResult:
    """Add a current memory about the session's person in its scope."""
    scope = await _scope_of(session_id)
    result = await MemoryStore().save_observation(
        ObservationInput(
            text=text,
            project=scope.namespace,
            type=observation_type,
            identity_key=scope.person.identity_key,
            subject=scope.subject,
            subject_owner=scope.subject_owner,
            principal=scope.person.principal,
            state=MemoryState.CURRENT,
            source_session_id=session_id,
        )
    )
    logger.info(_MEMORY_ADDED_EVENT, session_id=session_id, observation_id=result.id, namespace=scope.namespace)
    return result


async def _current_memory_in_scope(
    db_session: AsyncSession, scope: MemoryScope, observation_id: int
) -> db_models.MemoryObservation:
    """The current memory a change targets, or the refusal that says it is outside the scope."""
    row = await db_session.get(db_models.MemoryObservation, observation_id)
    if (
        row is None
        or row.project != scope.namespace
        or row.identity_key != scope.person.identity_key
        or row.state != MemoryState.CURRENT.value
    ):
        raise CurationRefusedError(
            CurationRefusalReason.OUT_OF_SCOPE, session_id=scope.session_id, observation_id=observation_id
        )
    return row


async def update_memory(session_id: str, observation_id: int, text: str) -> None:
    """Replace the statement of a current memory in the session's scope."""
    scope = await _scope_of(session_id)
    async with db._session() as db_session:
        row = await _current_memory_in_scope(db_session, scope, observation_id)
        row.narrative = text
        row.title = auto_title(text)
        db_session.add(row)
        await db_session.commit()
    logger.info(_MEMORY_UPDATED_EVENT, session_id=session_id, observation_id=observation_id)


async def retire_memory(session_id: str, observation_id: int) -> None:
    """Retire a current memory in the session's scope: it leaves use and stays recorded."""
    scope = await _scope_of(session_id)
    async with db._session() as db_session:
        row = await _current_memory_in_scope(db_session, scope, observation_id)
        row.state = MemoryState.RETIRED.value
        row.retired_at = datetime.now(UTC).isoformat()
        db_session.add(row)
        await db_session.commit()
    logger.info(_MEMORY_RETIRED_EVENT, session_id=session_id, observation_id=observation_id)


async def record_prospect(session_id: str, observation_type: ObservationType, text: str) -> ObservationResult:
    """Collect a business item from a desk conversation as a prospect for the home that owns the desk."""
    scope = await _scope_of(session_id)
    if scope.desk_home is None:
        raise CurationRefusedError(CurationRefusalReason.NOT_A_DESK, session_id=session_id)
    result = await MemoryStore().save_observation(
        ObservationInput(
            text=text,
            project=scope.desk_home.namespace,
            type=observation_type,
            subject=scope.desk_home.subject,
            subject_owner=scope.desk_home.subject_owner,
            state=MemoryState.PROSPECT,
            source_session_id=session_id,
        )
    )
    logger.info(
        _PROSPECT_RECORDED_EVENT,
        session_id=session_id,
        observation_id=result.id,
        namespace=scope.desk_home.namespace,
    )
    return result


async def advance_read_point(session_id: str, newest_entry_read: datetime) -> datetime | None:
    """Advance the conversation's read point to the newest entry read; it never moves backwards.

    Returns the read point after the call.
    """
    scope = await _scope_of(session_id)
    if scope.read_point is not None and newest_entry_read <= scope.read_point:
        return scope.read_point
    await db.update_session(session_id, last_memory_extraction_at=newest_entry_read.isoformat())
    logger.info(_READ_POINT_ADVANCED_EVENT, session_id=session_id, read_point=newest_entry_read.isoformat())
    return newest_entry_read
