"""Memory event declarations: extractions released for a memory worker to handle."""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import MemoryScopeRef

_EXTRACTION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)


class MemoryExtractionRequestedData(EventData):
    extraction_id: str
    identity: str
    desk: str | None = None
    source_session_id: str


class MemoryExtractionRequested(PlatformEvent[MemoryScopeRef, MemoryExtractionRequestedData]):
    NAME = "teleclaude.memory.extraction.requested"
    DESCRIPTION = (
        "A stretch of a conversation is released for a memory worker to read and keep the memories of the person "
        "or visitor it names current, at the desk it names or in their own home"
    )
    HOME_KINDS = _EXTRACTION_HOMES


DECLARED: tuple[DeclaredEvent, ...] = (MemoryExtractionRequested,)
