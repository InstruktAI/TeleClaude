"""Closed delivery-mode vocabulary for event subscriptions."""

from __future__ import annotations

from enum import StrEnum

_EVENT_SUBSCRIPTION_MODE_ONCE = "once"
_EVENT_SUBSCRIPTION_MODE_EVERY = "every"


class EventSubscriptionMode(StrEnum):
    """Whether a subscription is spent on its first matching event."""

    ONCE = _EVENT_SUBSCRIPTION_MODE_ONCE
    EVERY = _EVENT_SUBSCRIPTION_MODE_EVERY
