"""Route notification events into durable outbox rows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

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
            row_id = await self.db.enqueue_notification(
                channel=channel,
                recipient_email=recipient.email,
                content=content,
                file_path=file,
            )
            recipient_rows.append(row_id)

        logger.info(
            "Queued notification rows",
            channel=channel,
            recipient_count=len(recipient_rows),
        )
        return recipient_rows
