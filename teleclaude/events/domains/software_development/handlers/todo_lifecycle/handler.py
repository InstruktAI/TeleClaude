"""Todo lifecycle cartridge — planning event observer for the software-development domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    """Observe planning events and pass them through.

    Notifies on DOR assessment; silently passes other planning events.
    """
    et = event.event

    if et == "domain.software-development.planning.dor_assessed":
        # This event is already marked actionable/notifiable in the catalog.
        # The domain pipeline's autonomy matrix controls whether to surface it.
        pass

    return event
