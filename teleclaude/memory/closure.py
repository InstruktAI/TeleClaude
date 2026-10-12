"""Closure intake and extraction release: an eligible conversation's closure becomes one bounded extraction.

Agent runtime says which closures are eligible and when they happened; session mirrors say how far the
conversation's mirror covers them; this module decides when a stretch is released. A closure is captured once from
its ending event. A stretch is released only once the mirror's coverage is ready for it, starts exactly where the
source's completed progress ends, and ends at the last message recorded by the newest covered closure. At most one
extraction is open per source, so progress can never skip unfinished work.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.identity import canonical_memory_identity, memory_person_for_session
from teleclaude.core.models import EndpointStamp, HelpDeskKind, Session
from teleclaude.core.session_ended import is_conversation_session
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHome, EventHomeKind, EventHomeRef, EventLevel, ReceivedEvent, occurrence_id
from teleclaude.events.producer import publish_event
from teleclaude.events.references import MemoryScopeRef
from teleclaude.events.schemas.memory import MemoryExtractionRequested, MemoryExtractionRequestedData
from teleclaude.events.schemas.session_mirrors import MirrorCovered, MirrorCoveredData
from teleclaude.events.schemas.system import HelpDeskSessionEnded, PersonSessionEnded, SessionEndedData
from teleclaude.events.type_pattern import TypePattern
from teleclaude.events.wire import LegacyFacts
from teleclaude.memory import extractions
from teleclaude.memory.transition_barrier import transition_is_complete
from teleclaude.mirrors.messages import ConversationMessage, SessionCoverage, read_conversation_messages

logger = get_logger(__name__)

MEMORY_CLOSURE_CONSUMER = "memory-closure"
_PRODUCER = "memory"
_ZULU_DESIGNATOR = "Z"
_UTC_OFFSET = "+00:00"
_DESK_SEPARATOR = "@"
_NOT_ELIGIBLE_EVENT = "memory_closure_not_eligible"
_UNATTRIBUTABLE_EVENT = "memory_closure_unattributable"
_HELD_EVENT = "memory_extraction_held"
_NOTHING_TO_EXTRACT_EVENT = "memory_extraction_nothing_to_extract"
_REQUEST_PUBLISHED_EVENT = "memory_extraction_requested"
_REASON_NO_MIRROR = "the session has no conversation mirror yet"
_REASON_NOT_READY = "mirror coverage is not ready: a source present on disk failed or is not yet read"
_REASON_SCOPE_BUSY = (
    "an extraction for the same person and desk, prepared under another account of theirs, is still open"
)
_SCOPE_BUSY_EVENT = "memory_extraction_scope_busy"
_REASON_NOT_COVERED = "mirror coverage does not yet reach the closure"
_REASON_UNATTRIBUTABLE = "the session names no identity whose memories could be kept"
_REASON_NOT_PUBLISHED = "the extraction request could not be published: {error}"

_source_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass(frozen=True)
class _Scope:
    """Who a closure's memories are about, where they are kept, and the home that answers for them."""

    identity_key: str
    desk: str | None
    home: EventHome

    @property
    def home_kind(self) -> str:
        return self.home.kind.value if isinstance(self.home, EventHomeRef) else ""

    @property
    def home_slug(self) -> str:
        return self.home.instance if isinstance(self.home, EventHomeRef) else ""


def _scope_of(session: Session) -> _Scope | None:
    """The identity and desk a session's conversation is about, and the home that answers for it."""
    person = memory_person_for_session(session)
    if person is None:
        return None
    stamp = EndpointStamp.from_session(session)
    if stamp is not None and stamp.is_help_desk and stamp.desk_kind is not None and stamp.slug is not None:
        home_kind = EventHomeKind.COMPANY if stamp.desk_kind is HelpDeskKind.COMPANY else EventHomeKind.PROJECT
        return _Scope(
            person.identity_key,
            DeskIdentifier(stamp.desk_kind, stamp.slug).render(),
            EventHomeRef(home_kind, stamp.slug),
        )
    if person.person_slug is None:
        return None
    return _Scope(person.identity_key, None, EventHomeRef(EventHomeKind.PERSON, person.person_slug))


def scope_subject(identity: str, desk: str | None) -> str:
    """The subject identity of a scope's extractions: the identity, plus ``@<desk>`` at a help desk."""
    return identity if desk is None else f"{identity}{_DESK_SEPARATOR}{desk}"


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace(_ZULU_DESIGNATOR, _UTC_OFFSET))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _effective_instants(messages: Sequence[ConversationMessage]) -> list[datetime | None]:
    """Each message's recorded instant; a message without one takes its predecessor's."""
    instants: list[datetime | None] = []
    previous: datetime | None = None
    for message in messages:
        recorded = _instant(message.timestamp)
        previous = recorded or previous
        instants.append(previous)
    return instants


def _stretch_start(
    messages: Sequence[ConversationMessage],
    instants: Sequence[datetime | None],
    progress: db_models.MemorySourceProgress | None,
) -> int:
    """Where the next stretch begins: just after the completed message, else after the recorded time bound."""
    if progress is None:
        return 0
    if progress.through_key is not None:
        for index, message in enumerate(messages):
            if message.key == progress.through_key:
                return index + 1
    bound = max(
        (value for value in (_instant(progress.through_at), _instant(progress.time_bound)) if value is not None),
        default=None,
    )
    if bound is None:
        return 0
    for index, instant in enumerate(instants):
        if instant is not None and instant > bound:
            return index
    return len(messages)


def _stretch_end(instants: Sequence[datetime | None], start: int, bound: datetime) -> int:
    """One past the last message recorded at or before the closure that bounds the stretch."""
    end = start
    for index in range(start, len(instants)):
        instant = instants[index]
        if instant is not None and instant > bound:
            break
        end = index + 1
    return end


def extraction_stretch(
    extraction: db_models.MemoryExtraction,
    messages: Sequence[ConversationMessage],
    progress: db_models.MemorySourceProgress | None,
) -> list[ConversationMessage]:
    """The messages a released extraction covers, from where its source's progress stood to where it ends."""
    instants = _effective_instants(messages)
    start = _stretch_start(messages, instants, progress)
    end = min(start + extraction.message_count, len(messages))
    for index in range(start, len(messages)):
        if messages[index].key == extraction.through_key:
            end = index + 1
            break
    return list(messages[start:end])


def _covers(coverage: SessionCoverage | None, closure: db_models.MemoryClosure) -> str | None:
    """Why the coverage does not release this closure, or ``None`` when it does."""
    if coverage is None:
        return _REASON_NO_MIRROR
    if not coverage.ready:
        return _REASON_NOT_READY
    covered_at = _instant(coverage.covered_at)
    ended_at = _instant(closure.ended_at)
    if covered_at is None or ended_at is None or covered_at < ended_at:
        return _REASON_NOT_COVERED
    return None


async def _publish_request(extraction: db_models.MemoryExtraction) -> None:
    home = EventHomeRef(EventHomeKind(extraction.home_kind), extraction.home_slug)
    await publish_event(
        MemoryExtractionRequested(
            id=occurrence_id(extraction.id),
            subject=MemoryScopeRef(scope_subject(extraction.identity_key, extraction.desk)),
            home=home,
            data=MemoryExtractionRequestedData(
                extraction_id=extraction.id,
                identity=extraction.identity_key,
                desk=extraction.desk,
                source_session_id=extraction.source_session_id,
            ),
        ),
        LegacyFacts(producer=_PRODUCER, level=EventLevel.WORKFLOW, domain=_PRODUCER),
    )
    logger.info(_REQUEST_PUBLISHED_EVENT, extraction_id=extraction.id, source_session_id=extraction.source_session_id)


async def allocate(source_session_id: str) -> None:
    """Release the next stretch of a source conversation, if a covered closure is waiting and none is open.

    Safe to call at any time and any number of times: it releases nothing while an extraction is open, while the
    transition is incomplete, or while no pending closure is covered.
    """
    async with _source_locks[source_session_id]:
        pending = await extractions.pending_closures(source_session_id)
        if not pending or not await transition_is_complete():
            return
        if await extractions.open_extraction(source_session_id) is not None:
            return
        conversation = await asyncio.to_thread(read_conversation_messages, source_session_id)
        coverage = conversation.coverage if conversation is not None else None
        covered: list[db_models.MemoryClosure] = []
        for closure in pending:
            reason = _covers(coverage, closure)
            if reason is None:
                covered.append(closure)
            else:
                await extractions.set_closure_reason([closure.id], reason)
                logger.info(_HELD_EVENT, source_session_id=source_session_id, closure_id=closure.id, reason=reason)
        if not covered or conversation is None:
            return
        await _release(source_session_id, conversation.messages, coverage, covered)


async def _scope_has_rival(identity_key: str, desk: str | None) -> bool:
    """Whether an open extraction names the same person and desk under another spelling, so another worker holds it.

    An account later bound to a registered person and that person are one scope with two subjects; their workers
    would otherwise write the one collection at the same time.
    """
    canonical = canonical_memory_identity(identity_key)
    return any(
        open_extraction.identity_key != identity_key
        and canonical_memory_identity(open_extraction.identity_key) == canonical
        for open_extraction in await extractions.open_extractions_at(desk)
    )


async def _release(
    source_session_id: str,
    messages: Sequence[ConversationMessage],
    coverage: SessionCoverage | None,
    covered: Sequence[db_models.MemoryClosure],
) -> None:
    newest = max(covered, key=lambda closure: _instant(closure.ended_at) or datetime.min.replace(tzinfo=UTC))
    async with extractions.scope_claim(extractions.claim_key(newest.desk, newest.identity_key)):
        if await _scope_has_rival(newest.identity_key, newest.desk):
            await extractions.set_closure_reason([closure.id for closure in covered], _REASON_SCOPE_BUSY)
            logger.info(_SCOPE_BUSY_EVENT, source_session_id=source_session_id, desk=newest.desk, closures=len(covered))
            return
        await _release_scoped(source_session_id, messages, coverage, covered, newest)


async def _release_scoped(
    source_session_id: str,
    messages: Sequence[ConversationMessage],
    coverage: SessionCoverage | None,
    covered: Sequence[db_models.MemoryClosure],
    newest: db_models.MemoryClosure,
) -> None:
    bound = _instant(newest.ended_at)
    progress = await extractions.get_progress(source_session_id)
    instants = _effective_instants(messages)
    start = _stretch_start(messages, instants, progress)
    end = _stretch_end(instants, start, bound) if bound is not None else start
    closure_ids = [closure.id for closure in covered]
    if end <= start:
        await extractions.satisfy_empty_closures(closure_ids)
        logger.info(_NOTHING_TO_EXTRACT_EVENT, source_session_id=source_session_id, closures=len(closure_ids))
        return
    stretch = messages[start:end]
    last_instant = instants[end - 1]
    missing = sorted(
        {source.source_identity for source in (coverage.missing_sources if coverage else ())}
        & {message.source_identity for message in stretch}
    )
    extraction = await extractions.release_extraction(
        extractions.ExtractionRelease(
            source_session_id=source_session_id,
            identity_key=newest.identity_key,
            desk=newest.desk,
            home_kind=newest.home_kind,
            home_slug=newest.home_slug,
            from_key=progress.through_key if progress is not None else None,
            through_key=stretch[-1].key,
            through_at=last_instant.isoformat() if last_instant is not None else None,
            message_count=len(stretch),
            missing_sources=missing,
            closure_ids=closure_ids,
        )
    )
    try:
        await _publish_request(extraction)
    except Exception as exc:
        # An extraction nobody was told about would stay open forever and hold the source's later stretches.
        await extractions.fail_extraction(extraction.id, _REASON_NOT_PUBLISHED.format(error=exc))
        raise


async def intake_closure(event: ReceivedEvent) -> None:
    """Capture an eligible conversation's closure from its ending event, then release what is covered."""
    ended = SessionEndedData.model_validate(event.data)
    session = await db.get_session(ended.session_id)
    if session is None or not is_conversation_session(session):
        logger.info(_NOT_ELIGIBLE_EVENT, session_id=ended.session_id)
        return
    scope = _scope_of(session)
    if scope is None:
        await extractions.record_failed_extraction(
            source_session_id=ended.session_id,
            identity_key="",
            desk=None,
            home_kind="",
            home_slug="",
            reason=_REASON_UNATTRIBUTABLE,
        )
        logger.warning(_UNATTRIBUTABLE_EVENT, session_id=ended.session_id)
        return
    await extractions.record_closure(
        extractions.ClosureCapture(
            id=event.id,
            source_session_id=ended.session_id,
            ended_at=ended.ended_at,
            identity_key=scope.identity_key,
            desk=scope.desk,
            home_kind=scope.home_kind,
            home_slug=scope.home_slug,
        )
    )
    await allocate(ended.session_id)


async def on_mirror_covered(event: ReceivedEvent) -> None:
    """Release what a session's newly reported mirror coverage now covers."""
    covered = MirrorCoveredData.model_validate(event.data)
    await allocate(covered.session_id)


async def allocate_all_pending() -> None:
    """Release every source conversation's covered closures; the recovery path after a restart or a barrier."""
    for source_session_id in await extractions.sources_with_pending_closures():
        await allocate(source_session_id)


async def _route(event: ReceivedEvent) -> None:
    if event.type == MirrorCovered.type_name():
        await on_mirror_covered(event)
        return
    await intake_closure(event)


def build_memory_closure_consumer() -> Consumer:
    """The consumer that turns eligible closures and reported mirror coverage into released extractions."""
    return Consumer(
        name=MEMORY_CLOSURE_CONSUMER,
        interest=Interest(
            types=(
                TypePattern(PersonSessionEnded.type_name()),
                TypePattern(HelpDeskSessionEnded.type_name()),
                TypePattern(MirrorCovered.type_name()),
            ),
            own_computer_only=True,
        ),
        handler=_route,
    )
