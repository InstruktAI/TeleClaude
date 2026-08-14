"""Shared push-message formatting for the external delivery adapters."""

from __future__ import annotations

from teleclaude.events.cartridges.notification import PushNotificationChange

_ACTION_CARD_TEMPLATE = "[TeleClaude - Action · {topic} · {occurred_at}]\n\n{summary}\nAction: {action}."


def format_notification_message(change: PushNotificationChange) -> str:
    """Render the push message shape shared by every delivery surface."""
    assert change.human_action is not None
    occurred_at = change.occurred_at.replace("+00:00", "Z")[:16] + "Z"
    return _ACTION_CARD_TEMPLATE.format(
        topic=change.human_action.topic,
        occurred_at=occurred_at,
        summary=change.human_action.summary,
        action=change.human_action.action,
    )
