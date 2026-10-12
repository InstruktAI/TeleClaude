"""Memory-owned extraction state: captured closures, released extractions and per-source progress.

A closure is captured once from an ending's own identity. An extraction is one bounded stretch of one source
conversation released to a memory worker; at most one is open per source, and it starts exactly where that
source's completed progress ends. Progress moves only when an extraction declares its stretch finished.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from instrukt_ai_logging import get_logger
from sqlmodel import col, select

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.memory.types import ExtractionStatus

logger = get_logger(__name__)

_CLOSURE_CAPTURED_EVENT = "memory_closure_captured"
_EXTRACTION_RELEASED_EVENT = "memory_extraction_released"
_EXTRACTION_COMPLETED_EVENT = "memory_extraction_completed"
_EXTRACTION_FAILED_EVENT = "memory_extraction_failed"
_PROGRESS_TIME_BOUND_EVENT = "memory_progress_time_bound_recorded"


@dataclass(frozen=True)
class ClosureCapture:
    """One eligible closure as its ending event stated it, with the scope its memories belong to."""

    id: str
    source_session_id: str
    ended_at: str
    identity_key: str
    desk: str | None
    home_kind: str
    home_slug: str


@dataclass(frozen=True)
class ExtractionRelease:
    """A stretch of a source conversation to release, and the pending closures it satisfies."""

    source_session_id: str
    identity_key: str
    desk: str | None
    home_kind: str
    home_slug: str
    from_key: str | None
    through_key: str
    through_at: str | None
    message_count: int
    missing_sources: Sequence[str]
    closure_ids: Sequence[str]


_scope_claims: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def claim_key(desk: str | None, identity_key: str) -> str:
    """What one scope's claim is keyed by: the desk, or for a personal home the person's own key.

    A verified account binding changes how a provider account relates to a person, never which desk a scope is
    at, so the key holds across a binding.
    """
    return desk if desk is not None else identity_key


@asynccontextmanager
async def scope_claim(key: str) -> AsyncIterator[None]:
    """Hold one scope for a whole interval: the decision about who may handle it, and the effect of that decision."""
    async with _scope_claims[key]:
        yield


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def record_closure(capture: ClosureCapture) -> bool:
    """Capture a closure once; ``True`` when it is new, ``False`` when this ending was already captured."""
    async with db._session() as session:
        if await session.get(db_models.MemoryClosure, capture.id) is not None:
            return False
        session.add(
            db_models.MemoryClosure(
                id=capture.id,
                source_session_id=capture.source_session_id,
                ended_at=capture.ended_at,
                identity_key=capture.identity_key,
                desk=capture.desk,
                home_kind=capture.home_kind,
                home_slug=capture.home_slug,
                created_at=_now(),
            )
        )
        await session.commit()
    logger.info(_CLOSURE_CAPTURED_EVENT, closure_id=capture.id, source_session_id=capture.source_session_id)
    return True


async def pending_closures(source_session_id: str) -> list[db_models.MemoryClosure]:
    """The source's closures not yet satisfied by a released extraction, oldest ending first."""
    statement = (
        select(db_models.MemoryClosure)
        .where(db_models.MemoryClosure.source_session_id == source_session_id)
        .where(col(db_models.MemoryClosure.settled_at).is_(None))
        .order_by(col(db_models.MemoryClosure.ended_at))
    )
    async with db._session() as session:
        return list((await session.exec(statement)).all())


async def sources_with_pending_closures() -> list[str]:
    """The source conversations that have a closure awaiting extraction."""
    statement = (
        select(db_models.MemoryClosure.source_session_id)
        .where(col(db_models.MemoryClosure.settled_at).is_(None))
        .distinct()
    )
    async with db._session() as session:
        return [str(source) for source in (await session.exec(statement)).all()]


async def set_closure_reason(closure_ids: Sequence[str], reason: str | None) -> None:
    """Record why pending closures wait, or clear the reason when they no longer do."""
    if not closure_ids:
        return
    async with db._session() as session:
        for closure_id in closure_ids:
            closure = await session.get(db_models.MemoryClosure, closure_id)
            if closure is not None and closure.settled_at is None and closure.pending_reason != reason:
                closure.pending_reason = reason
                session.add(closure)
        await session.commit()


async def open_extraction(source_session_id: str) -> db_models.MemoryExtraction | None:
    """The source's released extraction that has neither completed nor failed, if any."""
    statement = (
        select(db_models.MemoryExtraction)
        .where(db_models.MemoryExtraction.source_session_id == source_session_id)
        .where(db_models.MemoryExtraction.status == ExtractionStatus.READY.value)
    )
    async with db._session() as session:
        return (await session.exec(statement)).first()


async def open_extractions_at(desk: str | None) -> list[db_models.MemoryExtraction]:
    """Every source's released extraction that has neither completed nor failed, for one desk (or no desk)."""
    statement = select(db_models.MemoryExtraction).where(
        db_models.MemoryExtraction.status == ExtractionStatus.READY.value
    )
    statement = statement.where(
        col(db_models.MemoryExtraction.desk).is_(None) if desk is None else db_models.MemoryExtraction.desk == desk
    )
    async with db._session() as session:
        return list((await session.exec(statement)).all())


async def get_extraction(extraction_id: str) -> db_models.MemoryExtraction | None:
    """The extraction with this id, whatever its status."""
    async with db._session() as session:
        return await session.get(db_models.MemoryExtraction, extraction_id)


async def get_progress(source_session_id: str) -> db_models.MemorySourceProgress | None:
    """How far the source conversation has been extracted, if it has been at all."""
    async with db._session() as session:
        return await session.get(db_models.MemorySourceProgress, source_session_id)


async def record_failed_extraction(
    *,
    source_session_id: str,
    identity_key: str,
    desk: str | None,
    home_kind: str,
    home_slug: str,
    reason: str,
) -> db_models.MemoryExtraction:
    """Record that a closure could not be turned into an extraction; nothing is dispatched and the reason stays visible."""
    now = _now()
    extraction = db_models.MemoryExtraction(
        id=str(uuid4()),
        source_session_id=source_session_id,
        identity_key=identity_key,
        desk=desk,
        home_kind=home_kind,
        home_slug=home_slug,
        status=ExtractionStatus.FAILED.value,
        reason=reason,
        created_at=now,
        updated_at=now,
    )
    async with db._session() as session:
        session.add(extraction)
        await session.commit()
    logger.warning(_EXTRACTION_FAILED_EVENT, extraction_id=extraction.id, reason=reason)
    return extraction


async def release_extraction(release: ExtractionRelease) -> db_models.MemoryExtraction:
    """Release a stretch and satisfy the closures it covers in one write."""
    now = _now()
    extraction = db_models.MemoryExtraction(
        id=str(uuid4()),
        source_session_id=release.source_session_id,
        identity_key=release.identity_key,
        desk=release.desk,
        home_kind=release.home_kind,
        home_slug=release.home_slug,
        from_key=release.from_key,
        through_key=release.through_key,
        through_at=release.through_at,
        message_count=release.message_count,
        missing_sources=json.dumps(list(release.missing_sources)),
        status=ExtractionStatus.READY.value,
        created_at=now,
        updated_at=now,
    )
    async with db._session() as session:
        session.add(extraction)
        for closure_id in release.closure_ids:
            closure = await session.get(db_models.MemoryClosure, closure_id)
            if closure is not None:
                closure.extraction_id = extraction.id
                closure.settled_at = now
                closure.pending_reason = None
                session.add(closure)
        await session.commit()
    logger.info(
        _EXTRACTION_RELEASED_EVENT,
        extraction_id=extraction.id,
        source_session_id=release.source_session_id,
        message_count=release.message_count,
    )
    return extraction


async def satisfy_empty_closures(closure_ids: Sequence[str]) -> None:
    """Settle closures whose stretch holds no messages: nothing to extract, nothing to dispatch."""
    async with db._session() as session:
        for closure_id in closure_ids:
            closure = await session.get(db_models.MemoryClosure, closure_id)
            if closure is not None and closure.settled_at is None:
                closure.settled_at = _now()
                closure.pending_reason = None
                session.add(closure)
        await session.commit()


async def complete_extraction(extraction_id: str) -> bool:
    """Declare an extraction's stretch finished and move its source's progress through it.

    Idempotent for a completed extraction. Returns ``False`` for an unknown extraction, a failed one, or one
    whose start no longer equals the source's progress: progress never moves backwards or past unfinished work.
    """
    async with db._session() as session:
        extraction = await session.get(db_models.MemoryExtraction, extraction_id)
        if extraction is None or extraction.status == ExtractionStatus.FAILED.value:
            return False
        if extraction.status == ExtractionStatus.COMPLETED.value:
            return True
        progress = await session.get(db_models.MemorySourceProgress, extraction.source_session_id)
        if (progress.through_key if progress is not None else None) != extraction.from_key:
            return False
        now = _now()
        if progress is None:
            progress = db_models.MemorySourceProgress(source_session_id=extraction.source_session_id, updated_at=now)
        progress.through_key = extraction.through_key
        progress.through_at = extraction.through_at
        progress.updated_at = now
        extraction.status = ExtractionStatus.COMPLETED.value
        extraction.updated_at = now
        session.add(progress)
        session.add(extraction)
        await session.commit()
    logger.info(
        _EXTRACTION_COMPLETED_EVENT, extraction_id=extraction_id, source_session_id=extraction.source_session_id
    )
    return True


async def fail_extraction(extraction_id: str, reason: str) -> bool:
    """Record why an extraction could not finish and make its stretch eligible again.

    The failed extraction stays visible with its reason; the closures it satisfied wait for a new allocation.
    Returns ``False`` for an unknown or already finished extraction.
    """
    async with db._session() as session:
        extraction = await session.get(db_models.MemoryExtraction, extraction_id)
        if extraction is None or extraction.status != ExtractionStatus.READY.value:
            return False
        extraction.status = ExtractionStatus.FAILED.value
        extraction.reason = reason
        extraction.updated_at = _now()
        session.add(extraction)
        closures = (
            await session.exec(
                select(db_models.MemoryClosure).where(db_models.MemoryClosure.extraction_id == extraction_id)
            )
        ).all()
        for closure in closures:
            closure.extraction_id = None
            closure.settled_at = None
            session.add(closure)
        await session.commit()
    logger.info(_EXTRACTION_FAILED_EVENT, extraction_id=extraction_id, reason=reason)
    return True


async def record_time_bound(source_session_id: str, bound: datetime) -> datetime | None:
    """Record that everything at or before this time is processed; it never moves earlier.

    Returns the time bound after the call.
    """
    iso = bound.isoformat()
    async with db._session() as session:
        progress = await session.get(db_models.MemorySourceProgress, source_session_id)
        if progress is None:
            progress = db_models.MemorySourceProgress(source_session_id=source_session_id, updated_at=_now())
        current = datetime.fromisoformat(progress.time_bound) if progress.time_bound else None
        if current is not None and bound <= current:
            return current
        progress.time_bound = iso
        progress.updated_at = _now()
        session.add(progress)
        await session.commit()
    logger.info(_PROGRESS_TIME_BOUND_EVENT, source_session_id=source_session_id, time_bound=iso)
    return bound
