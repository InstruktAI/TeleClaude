"""Feed monitor cartridge — bridges signal pipeline output into marketing feed events."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.envelope import EventEnvelope as Envelope
from teleclaude.events.envelope import EventLevel


async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    """Translate signal.synthesis.ready into domain.marketing.feed.synthesis_ready.

    Cross-domain bridge: consumes events from the signal pipeline namespace and
    re-emits them as marketing domain events for downstream automation.
    """
    if event.event != "signal.synthesis.ready":
        return None

    return Envelope(
        event="domain.marketing.feed.synthesis_ready",
        source="feed-monitor",
        level=EventLevel.WORKFLOW,
        domain="marketing",
        description="Signal synthesis ready for marketing review",
        payload={
            "synthesis_id": event.payload.get("synthesis_id", ""),
            "summary": event.payload.get("summary", ""),
            "source_event": event.event,
        },
    )
