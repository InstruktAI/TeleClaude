"""Shared push-message formatting for the external delivery adapters."""

from __future__ import annotations


def format_notification_message(event_type: str, notification_id: int, was_created: bool) -> str:
    """Render the push message shape shared by every delivery surface."""
    verb = "created" if was_created else "updated"
    return f"[{event_type}] Notification #{notification_id} {verb}."
