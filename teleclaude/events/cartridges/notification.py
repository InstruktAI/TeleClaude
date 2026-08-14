"""Notification projector cartridge — creates/updates/resolves SQLite notification rows."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db as core_db
from teleclaude.core.models import DiscordAdapterMetadata, HumanActionIntent
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext
from teleclaude.services.discord import DISCORD_BACKLINK_NO_GUILD, build_discord_jump_url

logger = get_logger(__name__)
_MISSING_GROUP_VALUE_LOG = "notification occurrence rejected: missing group value"


@dataclass(frozen=True)
class PushNotificationChange:
    """Projected notification change forwarded to push callbacks."""

    notification_id: int
    event_type: str
    level: int
    was_created: bool
    is_meaningful: bool
    actionable: bool
    group_identity: str
    delivery_debounce_s: float | None
    recipient: str | None
    human_action: HumanActionIntent | None
    event_id: str
    occurred_at: str
    discord_backlink_url: str | None
    discord_backlink_miss_reason: str | None


class NotificationProjectorCartridge:
    """Project event lifecycle changes into the notification table."""

    name = "notification-projector"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

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
        recipient_raw = event.payload.get("recipient")
        recipient = str(recipient_raw) if recipient_raw else None
        family = lc.family.value if lc.family else None

        if lc.group_key and not _group_value(event, lc.group_key):
            logger.error(_MISSING_GROUP_VALUE_LOG, event_type=event.event, group_key=lc.group_key)
            return event

        if lc.creates and lc.updates and lc.group_key:
            group_val = _group_value(event, lc.group_key)
            assert family is not None
            existing = await context.db.find_active_incident(family, lc.group_key, group_val, recipient)
            if existing:
                notification_id = existing["id"]
                is_meaningful = _meaningful_value_changed(event, existing["payload"], lc.meaningful_fields)
                await context.db.update_notification_fields(
                    notification_id,
                    event.description,
                    event.payload,
                    reset_human_status=is_meaningful,
                )
            else:
                notification_id, was_created = await context.db.upsert_by_idempotency_key(event, recipient, family)
                is_meaningful = True

        elif lc.creates:
            notification_id, was_created = await context.db.upsert_by_idempotency_key(event, recipient, family)

        elif lc.updates and lc.group_key:
            group_val = _group_value(event, lc.group_key)
            assert family is not None
            existing = await context.db.find_active_incident(family, lc.group_key, group_val, recipient)
            if existing:
                notification_id = existing["id"]
                # Determine if meaningful (reset to unseen) based on schema-declared fields
                is_meaningful = _meaningful_value_changed(event, existing["payload"], lc.meaningful_fields)
                await context.db.update_notification_fields(
                    notification_id,
                    event.description,
                    event.payload,
                    reset_human_status=is_meaningful,
                )
            else:
                # No existing notification for this group — create one
                notification_id, was_created = await context.db.upsert_by_idempotency_key(event, recipient, family)
                is_meaningful = True

        elif lc.resolves and lc.group_key:
            group_val = _group_value(event, lc.group_key)
            assert family is not None
            existing = await context.db.find_active_incident(family, lc.group_key, group_val, recipient)
            if existing:
                notification_id = existing["id"]
                await context.db.resolve_notification(notification_id, event.payload)

        if notification_id is not None:
            group_identity = str(notification_id)
            if lc.group_key:
                group_val = _group_value(event, lc.group_key)
                if group_val:
                    group_identity = group_val
            intent = event.human_action
            if intent is None:
                return event
            row = await context.db.get_notification(notification_id)
            if row is None or row["last_delivered_action_revision"] == intent.action_revision:
                return event
            await context.db.update_last_delivered_action_revision(notification_id, intent.action_revision)
            backlink_url, backlink_miss_reason = await _resolve_discord_backlink(intent.origin_session_id)
            await _invoke_push_callbacks(
                context,
                PushNotificationChange(
                    notification_id=notification_id,
                    event_type=event.event,
                    level=int(event.level),
                    was_created=was_created,
                    is_meaningful=is_meaningful,
                    actionable=schema.actionable,
                    group_identity=group_identity,
                    delivery_debounce_s=schema.delivery_debounce_s,
                    recipient=recipient,
                    human_action=intent,
                    event_id=event.event_id,
                    occurred_at=event.timestamp.isoformat(),
                    discord_backlink_url=backlink_url,
                    discord_backlink_miss_reason=backlink_miss_reason,
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
            result = cb(change)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception(
                "push callback failed",
                event_type=change.event_type,
                notification_id=change.notification_id,
            )


def _group_value(event: EventEnvelope, group_key: str) -> str:
    """Return the required non-empty payload value used as an incident key."""
    value = event.payload.get(group_key)
    return str(value).strip() if value is not None else ""


def _meaningful_value_changed(event: EventEnvelope, stored_payload: str, meaningful_fields: list[str]) -> bool:
    """Return whether a declared meaningful field differs from its stored value."""
    existing_payload = json.loads(stored_payload)
    return any(
        field_name in event.payload and event.payload[field_name] != existing_payload.get(field_name)
        for field_name in meaningful_fields
    )


async def _resolve_discord_backlink(origin_session_id: str | None) -> tuple[str | None, str | None]:
    """Resolve an optional origin session to its Discord jump URL once per push."""
    if origin_session_id is None:
        return None, None
    session = await core_db.get_session(origin_session_id)
    if session is None:
        return None, "unknown_session"
    origin = session.get_origin_section("discord")
    metadata = DiscordAdapterMetadata.from_dict(origin)
    destination = metadata.thread_id or metadata.channel_id
    if destination is None:
        return None, "no_destination" if origin else "no_discord_origin"
    jump_url = build_discord_jump_url(metadata.guild_id, destination, is_thread=metadata.thread_id is not None)
    if jump_url is None:
        return None, DISCORD_BACKLINK_NO_GUILD
    return jump_url, None
