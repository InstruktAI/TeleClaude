"""Role-based notification delivery primitives."""

from .discovery import NotificationRecipient, NotificationSubscriptionIndex
from .router import NotificationRouter
from .worker import NotificationOutboxWorker

__all__ = ["NotificationRouter", "NotificationOutboxWorker", "NotificationRecipient", "NotificationSubscriptionIndex"]
