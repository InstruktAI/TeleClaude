"""Deploy tracker cartridge — surfaces deploy events with failure escalation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    """Pass through deploy events; failed deployments are already marked actionable in the catalog."""
    return event
