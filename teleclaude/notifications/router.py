"""Route notification events into durable outbox rows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.schema import CredsConfig, SubscriptionNotification
from teleclaude.core import db as db_module

from .discovery import discover_notification_recipients_for_channel

if TYPE_CHECKING:
    from teleclaude.core.db import Db

logger = get_logger(__name__)


class NotificationRouter:
    """Resolve channel subscriptions and enqueue rows in notification_outbox."""

    def __init__(self, db: "Db | None" = None, root: Path | None = None) -> None:
        self.db = db or db_module.db
        self.root = root

    async def send_notification(self, channel: str, content: str, file: str | None = None) -> list[int]:
        """Resolve recipients for a channel and persist one outbox row each."""
        recipient_rows: list[int] = []
        subscribers = discover_notification_recipients_for_channel(channel, root=self.root)

        if not subscribers:
            logger.info("No notification subscribers found", channel=channel)
            return []

        for recipient in subscribers:
            try:
                row_id = await self.db.enqueue_notification(
                    channel=channel,
                    recipient_email=recipient.email,
                    content=content,
                    file_path=file,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "failed to enqueue notification for recipient",
                    channel=channel,
                    email=recipient.email,
                    error=str(exc),
                )
                continue
            recipient_rows.append(row_id)

        logger.info(
            "Queued notification rows",
            channel=channel,
            recipient_count=len(recipient_rows),
        )
        return recipient_rows

    async def enqueue_job_notifications(
        self,
        job_name: str,
        content: str,
        file_path: str | None,
        recipients: list[tuple[CredsConfig, SubscriptionNotification]],
    ) -> list[int]:
        """Enqueue outbox rows for each discovered job recipient.

        *recipients* comes from ``discover_job_recipients()`` and pairs each
        person's credentials with their notification preferences.
        """
        row_ids: list[int] = []

        for creds, notification in recipients:
            delivery_channel = notification.preferred_channel
            recipient_address = _resolve_recipient_address(creds, notification)
            if not recipient_address:
                logger.warning("no delivery address for recipient", job=job_name)
                continue

            try:
                row_id = await self.db.enqueue_notification(
                    channel=job_name,
                    recipient_email=recipient_address,
                    content=content,
                    file_path=file_path,
                    delivery_channel=delivery_channel,
                )
            except Exception as exc:
                logger.error(
                    "failed to enqueue job notification",
                    job=job_name,
                    address=recipient_address,
                    error=str(exc),
                )
                continue
            row_ids.append(row_id)

        logger.info(
            "Queued job notification rows",
            job=job_name,
            recipient_count=len(row_ids),
        )
        return row_ids


def _resolve_recipient_address(
    creds: CredsConfig,
    notification: SubscriptionNotification,
) -> str | None:
    """Derive the delivery address from creds and notification preferences."""
    channel = notification.preferred_channel

    if channel == "telegram" and creds.telegram and creds.telegram.chat_id:
        return creds.telegram.chat_id

    if channel == "email" and notification.email:
        return notification.email

    # Fallback: try telegram chat_id regardless of preferred channel
    if creds.telegram and creds.telegram.chat_id:
        return creds.telegram.chat_id

    return None
