"""Notification projector cartridge — creates/updates/resolves SQLite notification rows."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = get_logger(__name__)


class NotificationProjectorCartridge:
    name = "notification-projector"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        schema = context.catalog.get(event.event)
        if schema is None or schema.lifecycle is None:
            return event

        lc = schema.lifecycle
        notification_id: int | None = None
        was_created = False
        is_meaningful = False

        if lc.creates:
            notification_id, was_created = await context.db.upsert_by_idempotency_key(event, schema)

        elif lc.updates and lc.group_key:
            group_val = str(event.payload.get(lc.group_key, ""))
            existing = await context.db.find_by_group_key(lc.group_key, group_val)
            if existing:
                notification_id = existing["id"]
                # Determine if meaningful (reset to unseen) based on schema-declared fields
                changed_fields = set(event.payload.keys()) & set(lc.meaningful_fields)
                is_meaningful = bool(changed_fields)
                await context.db.update_notification_fields(
                    notification_id,
                    event.description,
                    event.payload,
                    reset_human_status=is_meaningful,
                )
            else:
                # No existing notification for this group — create one
                notification_id, was_created = await context.db.upsert_by_idempotency_key(event, schema)
                is_meaningful = True

        elif lc.resolves and lc.group_key:
            group_val = str(event.payload.get(lc.group_key, ""))
            existing = await context.db.find_by_group_key(lc.group_key, group_val)
            if existing:
                notification_id = existing["id"]
                await context.db.resolve_notification(notification_id, event.payload)

        if notification_id is not None:
            await _invoke_push_callbacks(context, notification_id, event.event, was_created, is_meaningful)

        return event


async def _invoke_push_callbacks(
    context: PipelineContext,
    notification_id: int,
    event_type: str,
    was_created: bool,
    is_meaningful: bool,
) -> None:
    for cb in context.push_callbacks:
        try:
            result = cb(notification_id, event_type, was_created, is_meaningful)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("push callback failed", event_type=event_type, notification_id=notification_id)
