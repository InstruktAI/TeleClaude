"""Deduplication cartridge — drops duplicate events by idempotency key."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)


class DeduplicationCartridge:
    name = "dedup"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        schema = context.catalog.get(event.event)
        if schema is None:
            return event

        key = context.catalog.build_idempotency_key(event.event, event.payload)
        if key is None:
            return event

        # Stamp the key onto the envelope so downstream cartridges can use it
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
