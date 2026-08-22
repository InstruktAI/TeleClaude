"""Shared push-message formatting for the external delivery adapters."""

from __future__ import annotations

from teleclaude.core.injected_text import EnvelopeField, EnvelopeName, render_bracket_envelope, semantic_envelope
from teleclaude.events.cartridges.notification import PushNotificationChange

_ACTION_BODY_TEMPLATE = "{summary}\nAction: {action}."
_UTC_MINUTE_SUFFIX = "Z"
_UTC_OFFSET_SUFFIX = "+00:00"
_UTC_MINUTE_LENGTH = 16


def format_notification_message(change: PushNotificationChange) -> str:
    """Render the push message shape shared by every delivery surface."""
    assert change.human_action is not None
    occurred_at = (
        change.occurred_at.replace(_UTC_OFFSET_SUFFIX, _UTC_MINUTE_SUFFIX)[:_UTC_MINUTE_LENGTH] + _UTC_MINUTE_SUFFIX
    )
    body = _ACTION_BODY_TEMPLATE.format(
        summary=change.human_action.summary,
        action=change.human_action.action,
    )
    return render_bracket_envelope(
        semantic_envelope(
            EnvelopeName.ACTION,
            fields={
                EnvelopeField.TOPIC: change.human_action.topic,
                EnvelopeField.OCCURRED_AT: occurred_at,
            },
            body=body,
        )
    )
