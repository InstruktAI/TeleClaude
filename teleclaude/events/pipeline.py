"""Pipeline runtime — sequential cartridge executor."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
_FAILING_STAGE_NOTE_PREFIX = "teleclaude_failing_stage="


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
    ai_client: object = None
    emit: Callable[..., Awaitable[object]] | None = None


class Cartridge(Protocol):
    """Protocol implemented by all pipeline cartridges."""

    name: str

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
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

    def register(self, cartridge: Cartridge) -> None:
        """Append a cartridge to the end of the processing chain."""
        self._cartridges.append(cartridge)

    async def execute(self, event: EventEnvelope) -> EventEnvelope | None:
        """Run an event through the system pipeline and trigger domain fan-out."""
        current: EventEnvelope | None = event
        for cartridge in self._cartridges:
            if current is None:
                return None
            try:
                current = await cartridge.process(current, self._context)
            except Exception as exc:
                exc.add_note(f"{_FAILING_STAGE_NOTE_PREFIX}{cartridge.name}")
                raise

        if current is not None and self._domain_runner is not None:
            await self._run_domain_pipelines(current)

        return current

    async def _run_domain_pipelines(self, event: EventEnvelope) -> None:
        """Run domain pipelines once the system pipeline completes."""
        try:
            results = await self._domain_runner.run_all(event, self._context)
            logger.debug("Domain pipeline results: %s", {k: v is not None for k, v in results.items()})
        except asyncio.CancelledError:
            logger.debug("Domain pipeline fan-out cancelled during shutdown")
            raise
