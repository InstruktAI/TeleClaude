"""Classification cartridge — annotates events with treatment and actionability."""

from __future__ import annotations

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext


class ClassificationCartridge:
    name = "classification"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        schema = context.catalog.get(event.event)

        if schema is None:
            treatment = "signal-only"
            actionable = False
        else:
            treatment = "notification-worthy" if schema.lifecycle is not None else "signal-only"
            actionable = schema.actionable

        updated_payload = dict(event.payload)
        updated_payload["_classification"] = {"treatment": treatment, "actionable": actionable}
        return event.model_copy(update={"payload": updated_payload})
