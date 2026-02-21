"""Discover notification subscribers from per-person config.

NOTE: Legacy channel-based notification discovery has been replaced by
subscription-driven job recipients (teleclaude.cron.job_recipients).
This module retains its public API for backward compatibility but returns
empty results.  Callers that still need channel-based routing should
migrate to the subscription model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotificationRecipient:
    """Resolved notification recipient."""

    email: str
    telegram_chat_id: str


@dataclass(frozen=True)
class NotificationSubscriptionIndex:
    """Channel -> recipients mapping."""

    by_channel: dict[str, list[NotificationRecipient]]

    def for_channel(self, channel: str) -> list[NotificationRecipient]:
        """Return recipients subscribed to a given channel."""
        return list(self.by_channel.get(channel, []))

    def get_chat_id(self, email: str) -> str | None:
        """Resolve chat ID for the given email."""
        for recipients in self.by_channel.values():
            for recipient in recipients:
                if recipient.email == email:
                    return recipient.telegram_chat_id
        return None


def build_notification_subscriptions(root: Path | None = None) -> NotificationSubscriptionIndex:
    """Build notification subscriptions grouped by channel.

    Returns an empty index — legacy channel-based notifications have been
    replaced by subscription-driven job recipients.
    """
    return NotificationSubscriptionIndex(by_channel={})


def discover_notification_recipients_for_channel(
    channel: str,
    *,
    root: Path | None = None,
) -> list[NotificationRecipient]:
    """Return all subscribers for one channel."""
    return build_notification_subscriptions(root).for_channel(channel)
