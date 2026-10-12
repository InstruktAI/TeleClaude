"""What a memory worker does with an extraction it was handed: read its material, finish it, or fail it.

Reading assembles the stretch the extraction covers from the session mirror's published conversation reader.
Finishing or failing settles the extraction in memory's own store and then lets the source's next covered stretch
be released, so a failed stretch is re-allocated without waiting for another closure.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from instrukt_ai_logging import get_logger
from sqlmodel import col, select

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.memory import extractions
from teleclaude.memory.closure import allocate, allocate_all_pending, extraction_stretch
from teleclaude.memory.curation import (
    CurationRefusalReason,
    CurationRefusedError,
    extraction_claim_key,
    require_scope_holder,
)
from teleclaude.memory.types import ExtractionStatus, MemoryState
from teleclaude.mirrors.messages import ConversationMessage, SessionCoverage, read_conversation_messages

logger = get_logger(__name__)

_EXTRACTION_REFUSED_EVENT = "memory_extraction_settle_refused"


@dataclass(frozen=True)
class ExtractionReading:
    """An extraction with the conversation material it covers, the coverage behind it and what it already yielded."""

    extraction: db_models.MemoryExtraction
    messages: list[ConversationMessage]
    coverage: SessionCoverage | None
    missing_sources: list[str]
    prospects: list[db_models.MemoryObservation]


async def _prospects_from(source_session_id: str) -> list[db_models.MemoryObservation]:
    statement = (
        select(db_models.MemoryObservation)
        .where(db_models.MemoryObservation.source_session_id == source_session_id)
        .where(db_models.MemoryObservation.state == MemoryState.PROSPECT.value)
        .order_by(col(db_models.MemoryObservation.id))
    )
    async with db._session() as session:
        return list((await session.exec(statement)).all())


async def read_extraction(extraction_id: str) -> ExtractionReading:
    """Read an extraction's conversation material; a completed extraction carries none, its work being done."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    prospects = await _prospects_from(extraction.source_session_id) if extraction.desk is not None else []
    missing = list(json.loads(extraction.missing_sources))
    if extraction.status == ExtractionStatus.COMPLETED.value:
        return ExtractionReading(extraction, [], None, missing, prospects)
    conversation = await asyncio.to_thread(read_conversation_messages, extraction.source_session_id)
    if conversation is None:
        return ExtractionReading(extraction, [], None, missing, prospects)
    progress = await extractions.get_progress(extraction.source_session_id)
    return ExtractionReading(
        extraction=extraction,
        messages=extraction_stretch(extraction, conversation.messages, progress),
        coverage=conversation.coverage,
        missing_sources=missing,
        prospects=prospects,
    )


async def complete(extraction_id: str) -> db_models.MemoryExtraction:
    """Declare an extraction finished, move its source's progress through it, and release what is next."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        if extraction.status == ExtractionStatus.READY.value:
            await require_scope_holder(extraction)
        if not await extractions.complete_extraction(extraction_id):
            logger.warning(_EXTRACTION_REFUSED_EVENT, extraction_id=extraction_id, status=extraction.status)
            raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_OPEN, session_id=extraction_id)
    await allocate(extraction.source_session_id)
    await allocate_all_pending()
    return await _settled(extraction_id)


async def fail(extraction_id: str, reason: str) -> db_models.MemoryExtraction:
    """Record that an extraction could not be finished, and release its stretch again with whatever else is covered."""
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    async with extractions.scope_claim(await extraction_claim_key(extraction_id)):
        if not await extractions.fail_extraction(extraction_id, reason):
            logger.warning(_EXTRACTION_REFUSED_EVENT, extraction_id=extraction_id, status=extraction.status)
            raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_OPEN, session_id=extraction_id)
    await allocate(extraction.source_session_id)
    await allocate_all_pending()
    return await _settled(extraction_id)


async def _settled(extraction_id: str) -> db_models.MemoryExtraction:
    extraction = await extractions.get_extraction(extraction_id)
    if extraction is None:
        raise CurationRefusedError(CurationRefusalReason.EXTRACTION_NOT_FOUND, session_id=extraction_id)
    return extraction
