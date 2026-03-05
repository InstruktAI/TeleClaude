"""Pipeline runtime — sequential cartridge executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope

if TYPE_CHECKING:
    from teleclaude_events.cartridges.correlation import CorrelationConfig
    from teleclaude_events.cartridges.trust import TrustConfig
    from teleclaude_events.producer import EventProducer


def _default_trust_config() -> Any:
    from teleclaude_events.cartridges.trust import TrustConfig

    return TrustConfig()


def _default_correlation_config() -> Any:
    from teleclaude_events.cartridges.correlation import CorrelationConfig

    return CorrelationConfig()


@dataclass
class PipelineContext:
    catalog: EventCatalog
    db: EventDB
    push_callbacks: list[Callable[..., object]] = field(default_factory=list)
    trust_config: TrustConfig = field(default_factory=_default_trust_config)
    correlation_config: CorrelationConfig = field(default_factory=_default_correlation_config)
    producer: EventProducer | None = None


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
