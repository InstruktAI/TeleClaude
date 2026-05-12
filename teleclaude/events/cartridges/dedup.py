"""Deduplication cartridge — drops duplicate deliveries by event identity."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)


class DeduplicationCartridge:
    """Reject known event identities while allowing new events for the same subject."""

    name = "dedup"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Stamp and enforce idempotency keys before projection work begins."""
        schema = context.catalog.get(event.event)
        if schema is None:
            return event

        # Stamp the producer-created event identity onto the envelope so downstream
        # cartridges can persist it as the durable replay deduplication key.
        key = event.event_id
        event = event.model_copy(update={"idempotency_key": key})

        # Updates-only schemas must not be deduplicated — each event updates the existing
        # notification and subsequent events for the same key must reach the projector.
        lc = schema.lifecycle
        if lc is not None and lc.updates and not lc.creates:
            return event

        if await context.db.idempotency_key_exists(key):
            logger.debug("dedup: dropping duplicate event", event=event.event, key=key)
            return None

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name
