"""Memory curation: the operations a memory agent uses to keep one person's memories current.

An operation addresses the person and scope it changes in one of two ways. The identity-addressed form names an
identity, optionally a desk, and an open extraction; memory verifies that all three agree with the extraction it
prepared, so a run cannot write outside the one person and scope it was handed. The session-addressed form names a
conversation session and derives the scope from that session's record; it remains for workers that began before
the identity-addressed contract. Memory applies the changes it is asked for and decides nothing about content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier, parse_entry_identifier
from teleclaude.core.identity import (
    MemoryPerson,
    canonical_memory_identity,
    memory_person_for_identity,
    memory_person_for_session,
    provider_identities_for_person,
)
from teleclaude.core.models import EndpointKind, EndpointStamp, HelpDeskKind, Session
from teleclaude.core.session_ended import is_conversation_session
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.memory import extractions
from teleclaude.memory.store import MemoryStore, auto_title, resolve_observation_project_scope
from teleclaude.memory.types import ExtractionStatus, MemoryState, ObservationInput, ObservationResult, ObservationType

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
_REFUSAL_OUT_OF_SCOPE = "Memory {observation_id} is not a current memory in the scope of {session_id}."
_REFUSAL_EXTRACTION_NOT_FOUND = "Extraction {session_id} was not found."
_REFUSAL_EXTRACTION_NOT_OPEN = (
    "Extraction {session_id} is not open: it has completed or failed, so it accepts no further changes."
)
_REFUSAL_SCOPE_MISMATCH = (
    "The identity and desk named do not match the scope extraction {session_id} was prepared for. "
    "Use the identity and desk from the extraction assignment."
)
_REFUSAL_EXTRACTION_OPEN = (
    "Session {session_id} has an extraction in progress; its read point moves when that extraction completes."
)
_REFUSAL_SCOPE_BUSY = (
    "Another extraction for the same person and desk, prepared under a different account of theirs, is being "
    "handled first. Wait for it to settle, or fail extraction {session_id} so it is released again."
)
_REFUSAL_UNKNOWN_IDENTITY = (
    "Identity {detail} names no registered person and no provider account. Use person:<slug> or <provider>:<account>."
)
_REFUSAL_DESK_REQUIRED = (
    "Identity {detail} is not a registered person, so its memories exist only at a help desk. Name the desk."
)
_REFUSAL_INVALID_DESK = "{detail} is not a help-desk identifier. Use hd-company-<slug> or hd-project-<slug>."


class CurationRefusalReason(StrEnum):
    """Why a curation operation changed nothing."""

    SESSION_NOT_FOUND = "session_not_found"
    NOT_A_CONVERSATION = "not_a_conversation"
    NO_PERSON = "no_person"
    NOT_A_DESK = "not_a_desk"
    OUT_OF_SCOPE = "out_of_scope"
    EXTRACTION_NOT_FOUND = "extraction_not_found"
    EXTRACTION_NOT_OPEN = "extraction_not_open"
    SCOPE_MISMATCH = "scope_mismatch"
    EXTRACTION_OPEN = "extraction_open"
    SCOPE_BUSY = "scope_busy"
    UNKNOWN_IDENTITY = "unknown_identity"
    DESK_REQUIRED = "desk_required"
    INVALID_DESK = "invalid_desk"


_REFUSAL_MESSAGES: dict[CurationRefusalReason, str] = {
    CurationRefusalReason.SESSION_NOT_FOUND: _REFUSAL_SESSION_NOT_FOUND,
    CurationRefusalReason.NOT_A_CONVERSATION: _REFUSAL_NOT_A_CONVERSATION,
    CurationRefusalReason.NO_PERSON: _REFUSAL_NO_PERSON,
    CurationRefusalReason.NOT_A_DESK: _REFUSAL_NOT_A_DESK,
    CurationRefusalReason.OUT_OF_SCOPE: _REFUSAL_OUT_OF_SCOPE,
    CurationRefusalReason.EXTRACTION_NOT_FOUND: _REFUSAL_EXTRACTION_NOT_FOUND,
    CurationRefusalReason.EXTRACTION_NOT_OPEN: _REFUSAL_EXTRACTION_NOT_OPEN,
    CurationRefusalReason.SCOPE_MISMATCH: _REFUSAL_SCOPE_MISMATCH,
    CurationRefusalReason.EXTRACTION_OPEN: _REFUSAL_EXTRACTION_OPEN,
    CurationRefusalReason.SCOPE_BUSY: _REFUSAL_SCOPE_BUSY,
    CurationRefusalReason.UNKNOWN_IDENTITY: _REFUSAL_UNKNOWN_IDENTITY,
    CurationRefusalReason.DESK_REQUIRED: _REFUSAL_DESK_REQUIRED,
    CurationRefusalReason.INVALID_DESK: _REFUSAL_INVALID_DESK,
}
_NOT_FOUND_STATUS = 404
_REFUSED_STATUS = 409


class CurationRefusedError(RuntimeError):
    """A curation operation was refused and changed nothing."""

    def __init__(
        self,
        reason: CurationRefusalReason,
        *,
        session_id: str = "",
        observation_id: int | None = None,
        detail: str = "",
    ) -> None:
        self.reason = reason
        super().__init__(
            _REFUSAL_MESSAGES[reason].format(session_id=session_id, observation_id=observation_id, detail=detail),
        )

    @property
    def http_status_code(self) -> int:
        """The HTTP status that reports this refusal."""
        not_found = {CurationRefusalReason.SESSION_NOT_FOUND, CurationRefusalReason.EXTRACTION_NOT_FOUND}
        return _NOT_FOUND_STATUS if self.reason in not_found else _REFUSED_STATUS


@dataclass(frozen=True)
class DeskHome:
    """The home that owns a desk, as prospects are recorded for it."""

    namespace: str
    subject: str
    subject_owner: str


@dataclass(frozen=True)
class MemoryScope:
    """One person in one memory namespace: a person's own memories, or the memories about them at one desk."""

    namespace: str
    person: MemoryPerson
    subject: str
    subject_owner: str
    desk_home: DeskHome | None
    aliases: tuple[str, ...] = ()

    @property
    def is_desk(self) -> bool:
        """Whether the scope is a help desk's."""
        return self.desk_home is not None

    @property
    def identity_keys(self) -> tuple[str, ...]:
        """Every identity key whose memories this scope holds: the person's, and at a desk the keys of their bound accounts."""
        return (self.person.identity_key, *self.aliases)


@dataclass(frozen=True)
class SessionScope:
    """The scope a conversation session defines, with the read point its memories have reached."""

    session_id: str
    scope: MemoryScope
    read_point: datetime | None


def _desk_home(stamp: EndpointStamp) -> DeskHome | None:
    """The home a desk stamp names, or ``None`` when the stamp does not name one."""
    if stamp.desk_kind is None or stamp.slug is None:
        return None
    if stamp.desk_kind is HelpDeskKind.COMPANY:
        subject = SubjectRef(ConfigSubjectKind.COMPANY, stamp.slug).to_token()
        return DeskHome(stamp.slug, subject, EventHomeOwnerMarker.NONE.value)
    subject, owner = resolve_observation_project_scope(stamp.slug)
    return DeskHome(stamp.slug, subject, owner)


def scope_for_person(person: MemoryPerson, desk: DeskIdentifier | None, home_name: str | None) -> MemoryScope | None:
    """The one composition of a memory scope from the person, the desk it is about, and the home it is kept in.

    A desk scope's namespace is the desk's identifier (every desk folder carries the same name, so the folder
    cannot tell desks apart); otherwise it is the name of the home the memories are kept in. A registered
    person's memories are about that person. An unregistered visitor's are about the desk's home, recorded under
    their own platform identity.
    """
    desk_home = _desk_home_of(desk) if desk is not None else None
    if desk is not None and desk_home is None:
        return None
    namespace = desk.render() if desk is not None else home_name
    if namespace is None:
        return None
    if person.person_slug is not None:
        subject = SubjectRef(ConfigSubjectKind.PERSON, person.person_slug).to_token()
        subject_owner = EventHomeOwnerMarker.NONE.value
    elif desk_home is not None:
        subject, subject_owner = desk_home.subject, desk_home.subject_owner
    else:
        subject, subject_owner = EventHomeMarker.UNKNOWN.value, EventHomeOwnerMarker.UNRESOLVED.value
    aliases = provider_identities_for_person(person.person_slug) if desk is not None and person.person_slug else ()
    return MemoryScope(
        namespace=namespace,
        person=person,
        subject=subject,
        subject_owner=subject_owner,
        desk_home=desk_home,
        aliases=aliases,
    )


def _desk_home_of(desk: DeskIdentifier) -> DeskHome | None:
    return _desk_home(EndpointStamp(kind=EndpointKind.HELP_DESK, desk_kind=desk.kind, slug=desk.slug))


def resolve_scope(identity: str, desk: str | None) -> MemoryScope:
    """The scope an identity (and optionally a desk) names, or the refusal that says why it names none.

    Without a desk the identity is a registered person's own memories. With one it is the memories about that
    person, or about that visitor's platform account, at that desk. Neither a working directory nor a source
    session selects either.
    """
    person = memory_person_for_identity(identity)
    if person is None:
        raise CurationRefusedError(CurationRefusalReason.UNKNOWN_IDENTITY, detail=identity)
    desk_identifier: DeskIdentifier | None = None
    if desk is not None:
        parsed = parse_entry_identifier(desk)
        if not isinstance(parsed, DeskIdentifier):
            raise CurationRefusedError(CurationRefusalReason.INVALID_DESK, detail=desk)
        desk_identifier = parsed
    elif not person.registered:
        raise CurationRefusedError(CurationRefusalReason.DESK_REQUIRED, detail=identity)
    scope = scope_for_person(person, desk_identifier, person.person_slug)
    if scope is None:
        raise CurationRefusedError(CurationRefusalReason.INVALID_DESK, detail=desk or identity)
    return scope


def _working_folder_name(session: Session) -> str | None:
    if not session.project_path:
        return None
    folder = Path(session.project_path) / session.subdir if session.subdir else Path(session.project_path)
    return folder.name


def memory_scope(session: Session) -> MemoryScope | None:
    """The scope a conversation session defines; ``None`` when the session names no person or namespace."""
    person = memory_person_for_session(session)
    if person is None:
        return None
    stamp = EndpointStamp.from_session(session)
    desk = (
        DeskIdentifier(stamp.desk_kind, stamp.slug)
        if stamp is not None and stamp.is_help_desk and stamp.desk_kind is not None and stamp.slug is not None
        else None
    )
    home_name = (
        person.person_slug
        if person.person_slug is not None and is_conversation_session(session)
        else _working_folder_name(session)
    )
    return scope_for_person(person, desk, home_name)


async def _read_point(session: Session) -> datetime | None:
    """How far the session's conversation has been read: its source progress, or else the time it began."""
    progress = await extractions.get_progress(session.session_id)
    if progress is None:
        return session.created_at
    reached = [datetime.fromisoformat(value) for value in (progress.through_at, progress.time_bound) if value]
    return max(reached) if reached else session.created_at


async def _scope_of(session_id: str) -> SessionScope:
    """The scope of a conversation session, or the refusal that names why it has none."""
    session = await db.get_session(session_id)
    if session is None:
        raise CurationRefusedError(CurationRefusalReason.SESSION_NOT_FOUND, session_id=session_id)
    if not is_conversation_session(session):
        raise CurationRefusedError(CurationRefusalReason.NOT_A_CONVERSATION, session_id=session_id)
    scope = memory_scope(session)
    if scope is None:
        raise CurationRefusedError(CurationRefusalReason.NO_PERSON, session_id=session_id)
    return SessionScope(session_id=session_id, scope=scope, read_point=await _read_point(session))


@dataclass(frozen=True)
class CurationTarget:
    """What a curation operation is applied to: a scope, and the provenance its writes record."""

    scope: MemoryScope
    source_session_id: str | None
    extraction_id: str | None
    reference: str
    read_point: datetime | None = None


@dataclass(frozen=True)
class ScopeListing:
    """A scope with the current memories in it and, for a desk conversation, the prospects it already yielded."""

    target: CurationTarget
    memories: list[db_models.MemoryObservation]
    prospects: list[db_models.MemoryObservation]

    @property
    def scope(self) -> MemoryScope:
        return self.target.scope


async def _session_target(session_id: str) -> CurationTarget:
    """The target a conversation session defines, from the session's own record."""
    session_scope = await _scope_of(session_id)
    return CurationTarget(
        scope=session_scope.scope,
        source_session_id=session_id,
        extraction_id=None,
        reference=session_id,
        read_point=session_scope.read_point,
    )


def _scope_claim_key(scope: MemoryScope) -> str:
    return extractions.claim_key(scope.namespace if scope.is_desk else None, scope.person.identity_key)


async def extraction_claim_key(extraction_id: str) -> str:
    """The claim key of the scope an extraction was released for."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    return extractions.claim_key(extraction.desk, extraction.identity_key)


async def require_scope_holder(extraction: db_models.MemoryExtraction) -> None:
    """Refuse an extraction while an earlier open one names the same person and desk under another spelling.

    Accounts that were separate visitors when their extractions were released can be bound to one person
    afterwards; the extraction released first then handles the scope alone, and the others wait or fail.
    """
    canonical = canonical_memory_identity(extraction.identity_key)
    rivals = [
        other
        for other in await extractions.open_extractions_at(extraction.desk)
        if other.identity_key != extraction.identity_key and canonical_memory_identity(other.identity_key) == canonical
    ]
    first = min(
        (*rivals, extraction),
        key=lambda candidate: (candidate.created_at, candidate.id),
    )
    if rivals and first.id != extraction.id:
        raise CurationRefusedError(CurationRefusalReason.SCOPE_BUSY, session_id=extraction.id)


async def _extraction_target(identity: str, desk: str | None, extraction_id: str) -> CurationTarget:
    """The target an open extraction prepared, provided the identity and desk named agree with it exactly."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    if extraction.status != ExtractionStatus.READY.value:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_OPEN, session_id=extraction_id)
    scope = resolve_scope(identity, desk)
    requested_desk = DeskIdentifier(*_desk_parts(desk)).render() if desk is not None else None
    if (
        scope.person.identity_key != canonical_memory_identity(extraction.identity_key)
        or requested_desk != extraction.desk
    ):
        raise CurationRefusedError(CurationRefusalReason.SCOPE_MISMATCH, session_id=extraction_id)
    await require_scope_holder(extraction)
    return CurationTarget(
        scope=scope,
        source_session_id=extraction.source_session_id,
        extraction_id=extraction.id,
        reference=extraction.id,
    )


def _desk_parts(desk: str) -> tuple[HelpDeskKind, str]:
    parsed = parse_entry_identifier(desk)
    if not isinstance(parsed, DeskIdentifier):
        raise CurationRefusedError(CurationRefusalReason.INVALID_DESK, detail=desk)
    return parsed.kind, parsed.slug


async def _list(target: CurationTarget) -> ScopeListing:
    scope = target.scope
    memories_statement = (
        select(db_models.MemoryObservation)
        .where(db_models.MemoryObservation.project == scope.namespace)
        .where(col(db_models.MemoryObservation.identity_key).in_(scope.identity_keys))
        .where(db_models.MemoryObservation.state == MemoryState.CURRENT.value)
        .order_by(col(db_models.MemoryObservation.id))
    )
    prospects: list[db_models.MemoryObservation] = []
    async with db._session() as session:
        memories = list((await session.exec(memories_statement)).all())
        if scope.is_desk and target.source_session_id is not None:
            prospects_statement = (
                select(db_models.MemoryObservation)
                .where(db_models.MemoryObservation.source_session_id == target.source_session_id)
                .where(db_models.MemoryObservation.state == MemoryState.PROSPECT.value)
                .order_by(col(db_models.MemoryObservation.id))
            )
            prospects = list((await session.exec(prospects_statement)).all())
    return ScopeListing(target=target, memories=memories, prospects=prospects)


async def list_scope(session_id: str) -> ScopeListing:
    """List the scope a conversation session defines: its current memories and its recorded prospects."""
    return await _list(await _session_target(session_id))


async def list_identity_scope(identity: str, desk: str | None) -> ScopeListing:
    """List the current memories of the scope an identity (and desk) names, aliases at the desk included."""
    scope = resolve_scope(identity, desk)
    return await _list(
        CurationTarget(scope=scope, source_session_id=None, extraction_id=None, reference=scope.namespace)
    )


async def _add(target: CurationTarget, observation_type: ObservationType, text: str) -> ObservationResult:
    scope = target.scope
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
            source_session_id=target.source_session_id,
            extraction_id=target.extraction_id,
        )
    )
    logger.info(_MEMORY_ADDED_EVENT, reference=target.reference, observation_id=result.id, namespace=scope.namespace)
    return result


async def _current_memory_in_scope(
    db_session: AsyncSession, target: CurationTarget, observation_id: int
) -> db_models.MemoryObservation:
    """The current memory a change targets, or the refusal that says it is outside the scope."""
    scope = target.scope
    row = await db_session.get(db_models.MemoryObservation, observation_id)
    if (
        row is None
        or row.project != scope.namespace
        or row.identity_key not in scope.identity_keys
        or row.state != MemoryState.CURRENT.value
    ):
        raise CurationRefusedError(
            CurationRefusalReason.OUT_OF_SCOPE, session_id=target.reference, observation_id=observation_id
        )
    return row


async def _update(target: CurationTarget, observation_id: int, text: str) -> None:
    async with db._session() as db_session:
        row = await _current_memory_in_scope(db_session, target, observation_id)
        row.narrative = text
        row.title = auto_title(text)
        row.extraction_id = target.extraction_id or row.extraction_id
        db_session.add(row)
        await db_session.commit()
    logger.info(_MEMORY_UPDATED_EVENT, reference=target.reference, observation_id=observation_id)


async def _retire(target: CurationTarget, observation_id: int) -> None:
    async with db._session() as db_session:
        row = await _current_memory_in_scope(db_session, target, observation_id)
        row.state = MemoryState.RETIRED.value
        row.retired_at = datetime.now(UTC).isoformat()
        row.extraction_id = target.extraction_id or row.extraction_id
        db_session.add(row)
        await db_session.commit()
    logger.info(_MEMORY_RETIRED_EVENT, reference=target.reference, observation_id=observation_id)


async def _prospect(target: CurationTarget, observation_type: ObservationType, text: str) -> ObservationResult:
    desk_home = target.scope.desk_home
    if desk_home is None:
        raise CurationRefusedError(CurationRefusalReason.NOT_A_DESK, session_id=target.reference)
    result = await MemoryStore().save_observation(
        ObservationInput(
            text=text,
            project=desk_home.namespace,
            type=observation_type,
            subject=desk_home.subject,
            subject_owner=desk_home.subject_owner,
            state=MemoryState.PROSPECT,
            source_session_id=target.source_session_id,
            extraction_id=target.extraction_id,
        )
    )
    logger.info(
        _PROSPECT_RECORDED_EVENT,
        reference=target.reference,
        observation_id=result.id,
        namespace=desk_home.namespace,
    )
    return result


async def add_memory(session_id: str, observation_type: ObservationType, text: str) -> ObservationResult:
    """Add a current memory about the session's person in its scope."""
    target = await _session_target(session_id)
    async with extractions.scope_claim(_scope_claim_key(target.scope)):
        return await _add(target, observation_type, text)


async def update_memory(session_id: str, observation_id: int, text: str) -> None:
    """Replace the statement of a current memory in the session's scope."""
    target = await _session_target(session_id)
    async with extractions.scope_claim(_scope_claim_key(target.scope)):
        await _update(target, observation_id, text)


async def retire_memory(session_id: str, observation_id: int) -> None:
    """Retire a current memory in the session's scope: it leaves use and stays recorded."""
    target = await _session_target(session_id)
    async with extractions.scope_claim(_scope_claim_key(target.scope)):
        await _retire(target, observation_id)


async def record_prospect(session_id: str, observation_type: ObservationType, text: str) -> ObservationResult:
    """Collect a business item from a desk conversation as a prospect for the home that owns the desk."""
    target = await _session_target(session_id)
    async with extractions.scope_claim(_scope_claim_key(target.scope)):
        return await _prospect(target, observation_type, text)


async def add_extraction_memory(
    identity: str, desk: str | None, extraction_id: str, observation_type: ObservationType, text: str
) -> ObservationResult:
    """Add a current memory about the extraction's person in its scope."""
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        return await _add(await _extraction_target(identity, desk, extraction_id), observation_type, text)


async def update_extraction_memory(
    identity: str, desk: str | None, extraction_id: str, observation_id: int, text: str
) -> None:
    """Replace the statement of a current memory in the extraction's scope."""
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        await _update(await _extraction_target(identity, desk, extraction_id), observation_id, text)


async def retire_extraction_memory(identity: str, desk: str | None, extraction_id: str, observation_id: int) -> None:
    """Retire a current memory in the extraction's scope: it leaves use and stays recorded."""
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        await _retire(await _extraction_target(identity, desk, extraction_id), observation_id)


async def record_extraction_prospect(
    desk: str, extraction_id: str, observation_type: ObservationType, text: str
) -> ObservationResult:
    """Collect a business item from the extraction's desk conversation as a prospect for the desk's home."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        return await _prospect(
            await _extraction_target(extraction.identity_key, desk, extraction_id), observation_type, text
        )


async def advance_read_point(session_id: str, newest_entry_read: datetime) -> datetime | None:
    """Record that everything the conversation held up to this time is read; it never moves backwards.

    Accepted only while no extraction is open for the conversation. Returns the read point after the call.
    """
    read_point = (await _scope_of(session_id)).read_point
    if read_point is not None and newest_entry_read <= read_point:
        return read_point
    if await extractions.open_extraction(session_id) is not None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_OPEN, session_id=session_id)
    await extractions.record_time_bound(session_id, newest_entry_read)
    logger.info(_READ_POINT_ADVANCED_EVENT, session_id=session_id, read_point=newest_entry_read.isoformat())
    return newest_entry_read
