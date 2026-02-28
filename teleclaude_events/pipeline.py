"""Pipeline runtime — sequential cartridge executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Protocol

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope

if TYPE_CHECKING:
    pass


@dataclass
class PipelineContext:
    catalog: EventCatalog
    db: EventDB
    push_callbacks: list[Callable[..., object]] = field(default_factory=list)


class Cartridge(Protocol):
    name: str

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None: ...


class Pipeline:
    def __init__(self, cartridges: list[Cartridge], context: PipelineContext) -> None:
        self._cartridges = cartridges
        self._context = context

    async def execute(self, event: EventEnvelope) -> EventEnvelope | None:
        current: EventEnvelope | None = event
        for cartridge in self._cartridges:
            if current is None:
                return None
            current = await cartridge.process(current, self._context)
        return current
