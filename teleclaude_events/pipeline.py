"""Pipeline runtime — sequential cartridge executor."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

from instrukt_ai_logging import get_logger

from teleclaude_events.catalog import EventCatalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import EventEnvelope

if TYPE_CHECKING:
    from teleclaude_events.cartridges.correlation import CorrelationConfig
    from teleclaude_events.cartridges.trust import TrustConfig
    from teleclaude_events.domain_pipeline import DomainPipelineRunner
    from teleclaude_events.producer import EventProducer

logger = get_logger(__name__)


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
    # Optional: AI client for signal pipeline cartridges
    ai_client: object | None = None
    # Optional: emit callback for cartridges that need to fire additional events
    emit: Callable[[EventEnvelope], Awaitable[object]] | None = None


class Cartridge(Protocol):
    name: str

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None: ...


class Pipeline:
    def __init__(
        self,
        cartridges: list[Cartridge],
        context: PipelineContext,
        domain_runner: DomainPipelineRunner | None = None,
    ) -> None:
        self._cartridges = cartridges
        self._context = context
        self._domain_runner = domain_runner

    def register(self, cartridge: Cartridge) -> None:
        """Append a cartridge to the end of the processing chain."""
        self._cartridges.append(cartridge)

    async def execute(self, event: EventEnvelope) -> EventEnvelope | None:
        current: EventEnvelope | None = event
        for cartridge in self._cartridges:
            if current is None:
                return None
            current = await cartridge.process(current, self._context)

        # Fan out to domain pipelines after system pipeline completes (fire-and-forget)
        if current is not None and self._domain_runner is not None:
            asyncio.create_task(
                self._run_domain_pipelines(current),
                name="domain_pipeline_fanout",
            )

        return current

    async def _run_domain_pipelines(self, event: EventEnvelope) -> None:
        try:
            results = await self._domain_runner.run_all(event, self._context)  # type: ignore[union-attr]
            logger.debug("Domain pipeline results: %s", {k: v is not None for k, v in results.items()})
        except asyncio.CancelledError:
            logger.debug("Domain pipeline fan-out cancelled during shutdown")
            raise
        except Exception as e:
            logger.error("Domain pipeline fan-out error: %s", e, exc_info=True)
