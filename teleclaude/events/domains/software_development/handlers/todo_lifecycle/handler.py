"""Todo lifecycle cartridge — planning event observer for the software-development domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: "EventEnvelope", context: "PipelineContext") -> "EventEnvelope | None":
    """Observe planning events and pass them through.

    Notifies on DOR assessment and todo activation; silently passes other planning events.
    """
    et = event.event

    if et in (
        "domain.software-development.planning.dor_assessed",
        "domain.software-development.planning.todo_activated",
    ):
        # These events are already marked actionable/notifiable in the catalog.
        # The domain pipeline's autonomy matrix controls whether to surface them.
        pass

    return event
