"""Classification cartridge — annotates events with treatment and actionability."""

from __future__ import annotations

from teleclaude.events.notification_rules import rule_for
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.wire import StreamEvent


class ClassificationCartridge:
    """Classify events as notification-worthy or signal-only."""

    name = "classification"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Annotate the event data with its classification outcome."""
        rule = rule_for(event.type)

        if rule is None:
            treatment = "signal-only"
            actionable = False
        else:
            treatment = "notification-worthy" if rule.lifecycle is not None else "signal-only"
            actionable = rule.actionable

        updated_data = dict(event.data)
        updated_data["_classification"] = {"treatment": treatment, "actionable": actionable}
        return event.model_copy(update={"data": updated_data})

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
