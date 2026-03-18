"""Notification projector cartridge — creates/updates/resolves SQLite notification rows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)


@dataclass(frozen=True)
class PushNotificationChange:
    """Projected notification change forwarded to push callbacks."""

    notification_id: int
    event_type: str
    level: int
    was_created: bool
    is_meaningful: bool


class NotificationProjectorCartridge:
    """Project event lifecycle changes into the notification table."""

    name = "notification-projector"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Create, update, or resolve notifications based on event lifecycle metadata."""
        # Fast-path: if _classification is present and treatment is signal-only, skip notification logic
        classification = event.payload.get("_classification")
        if isinstance(classification, dict) and classification.get("treatment") == "signal-only":
            return event

        schema = context.catalog.get(event.event)
        if schema is None or schema.lifecycle is None:
            return event

        lc = schema.lifecycle
        notification_id: int | None = None
        was_created = False
        is_meaningful = False

        if lc.creates and lc.updates and lc.group_key:
            group_val = str(event.payload.get(lc.group_key, ""))
            existing = await context.db.find_by_group_key(lc.group_key, group_val)
            if existing:
                notification_id = existing["id"]
                changed_fields = set(event.payload.keys()) & set(lc.meaningful_fields)
                is_meaningful = bool(changed_fields)
                await context.db.update_notification_fields(
                    notification_id,
                    event.description,
                    event.payload,
                    reset_human_status=is_meaningful,
                )
            else:
                notification_id, was_created = await context.db.upsert_by_idempotency_key(event)
                is_meaningful = True

        elif lc.creates:
            notification_id, was_created = await context.db.upsert_by_idempotency_key(event)

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
                notification_id, was_created = await context.db.upsert_by_idempotency_key(event)
                is_meaningful = True

        elif lc.resolves and lc.group_key:
            group_val = str(event.payload.get(lc.group_key, ""))
            existing = await context.db.find_by_group_key(lc.group_key, group_val)
            if existing:
                notification_id = existing["id"]
                await context.db.resolve_notification(notification_id, event.payload)

        if notification_id is not None:
            await _invoke_push_callbacks(
                context,
                PushNotificationChange(
                    notification_id=notification_id,
                    event_type=event.event,
                    level=int(event.level),
                    was_created=was_created,
                    is_meaningful=is_meaningful,
                ),
            )

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name


async def _invoke_push_callbacks(context: PipelineContext, change: PushNotificationChange) -> None:
    """Invoke configured push callbacks for a projected notification change."""
    for cb in context.push_callbacks:
        try:
            result = cb(
                change.notification_id,
                change.event_type,
                change.level,
                change.was_created,
                change.is_meaningful,
            )
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "push callback failed",
                event_type=change.event_type,
                notification_id=change.notification_id,
            )
