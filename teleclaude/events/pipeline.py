"""Pipeline runtime — sequential cartridge executor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.db import EventDB
from teleclaude.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from teleclaude.events.cartridges.correlation import CorrelationConfig
    from teleclaude.events.cartridges.trust import TrustConfig
    from teleclaude.events.domain_pipeline import DomainPipelineRunner
    from teleclaude.events.producer import EventProducer

logger = get_logger(__name__)


def _default_trust_config() -> Any:
    """Build the default trust configuration lazily to avoid import cycles."""
    return import_module("teleclaude.events.cartridges.trust").TrustConfig()


def _default_correlation_config() -> Any:
    """Build the default correlation configuration lazily to avoid import cycles."""
    return import_module("teleclaude.events.cartridges.correlation").CorrelationConfig()


@dataclass
class PipelineContext:
    """Shared services and configuration available to every cartridge invocation."""

    catalog: EventCatalog
    db: EventDB
    push_callbacks: list[Callable[..., object]] = field(default_factory=list)
    trust_config: TrustConfig = field(default_factory=_default_trust_config)
    correlation_config: CorrelationConfig = field(default_factory=_default_correlation_config)
    producer: EventProducer | None = None


class Cartridge(Protocol):
    """Protocol implemented by all pipeline cartridges."""

    name: str

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Transform an event or return `None` to stop processing."""

    def describe(self) -> str:
        """Return a human-readable cartridge name for debug output."""
        return self.name


class Pipeline:
    """Execute the approved system pipeline and optionally fan out to domain pipelines."""

    def __init__(
        self,
        cartridges: list[Cartridge],
        context: PipelineContext,
        domain_runner: DomainPipelineRunner | None = None,
    ) -> None:
        self._cartridges = cartridges
        self._context = context
        self._domain_runner = domain_runner
        self._pending_fanout_tasks: set[asyncio.Task[None]] = set()

    def register(self, cartridge: Cartridge) -> None:
        """Append a cartridge to the end of the processing chain."""
        self._cartridges.append(cartridge)

    async def execute(self, event: EventEnvelope) -> EventEnvelope | None:
        """Run an event through the system pipeline and trigger domain fan-out."""
        current: EventEnvelope | None = event
        for cartridge in self._cartridges:
            if current is None:
                return None
            current = await cartridge.process(current, self._context)

        # Fan out to domain pipelines after system pipeline completes (fire-and-forget)
        if current is not None and self._domain_runner is not None:
            task = asyncio.create_task(
                self._run_domain_pipelines(current),
                name="domain_pipeline_fanout",
            )
            self._pending_fanout_tasks.add(task)
            task.add_done_callback(self._pending_fanout_tasks.discard)

        return current

    async def _run_domain_pipelines(self, event: EventEnvelope) -> None:
        """Run domain pipelines in the background once the system pipeline completes."""
        try:
            results = await self._domain_runner.run_all(event, self._context)
            logger.debug("Domain pipeline results: %s", {k: v is not None for k, v in results.items()})
        except asyncio.CancelledError:
            logger.debug("Domain pipeline fan-out cancelled during shutdown")
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Domain pipeline fan-out error: %s", e, exc_info=True)
