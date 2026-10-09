"""Pipeline context — the shared services a pipeline cartridge is invoked with."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.wire import StreamEvent

if TYPE_CHECKING:
    from teleclaude.events.db import EventDB
    from teleclaude.events.producer import EventProducer

_FAILING_STAGE_NOTE_PREFIX = "teleclaude_failing_stage="


@dataclass
class PipelineContext:
    """Shared services and configuration available to every cartridge invocation."""

    catalog: EventCatalog
    db: EventDB
    producer: EventProducer | None = None
    ai_client: object = None
    emit: Callable[..., Awaitable[object]] | None = None


class Cartridge(Protocol):
    """Protocol implemented by all pipeline cartridges."""

    name: str

    async def process(self, event: StreamEvent, context: PipelineContext, /) -> StreamEvent | None:
        """Transform an event or return `None` to stop processing."""

    def describe(self) -> str:
        """Return a human-readable cartridge name for debug output."""
        return self.name


def failing_stage_from_exception(exc: BaseException) -> str | None:
    """Return a pipeline failing-stage marker attached to an exception."""
    notes = getattr(exc, "__notes__", ())
    if not isinstance(notes, list):
        return None
    for note in reversed(notes):
        if isinstance(note, str) and note.startswith(_FAILING_STAGE_NOTE_PREFIX):
            return note.removeprefix(_FAILING_STAGE_NOTE_PREFIX)
    return None
