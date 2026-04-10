"""Campaign budget monitor cartridge — surfaces budget threshold hits for human review."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    """Pass through budget_threshold_hit events; marked actionable in catalog."""
    return event
