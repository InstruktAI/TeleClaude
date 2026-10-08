"""Deduplication cartridge — drops duplicate deliveries by event identity."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.events.notification_rules import rule_for
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.wire import StreamEvent

logger = get_logger(__name__)


class DeduplicationCartridge:
    """Reject known event identities while allowing new events for the same subject."""

    name = "dedup"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Stamp and enforce idempotency keys before projection work begins."""
        if context.catalog.get(event.type) is None:
            return event

        # Stamp the producer-created event identity onto the envelope so downstream
        # cartridges can persist it as the durable replay deduplication key.
        key = event.id
        event = event.model_copy(update={"legacy": event.legacy.model_copy(update={"idempotency_key": key})})

        # Updates-only schemas must not be deduplicated — each event updates the existing
        # notification and subsequent events for the same key must reach the projector.
        rule = rule_for(event.type)
        lc = rule.lifecycle if rule is not None else None
        if lc is not None and lc.updates and not lc.creates:
            return event

        if await context.db.idempotency_key_exists(key):
            logger.debug("dedup: dropping duplicate event", event=event.type, key=key)
            return None

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
