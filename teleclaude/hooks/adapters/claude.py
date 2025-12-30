"""Claude hook adapter - normalizes Claude Code payloads to internal schema."""

from __future__ import annotations

# Explicit mapping: Claude external field -> internal field
# Only these fields are forwarded; everything else is dropped
_CLAUDE_TO_INTERNAL: dict[str, str] = {
    "session_id": "session_id",
    "transcript_path": "transcript_path",
    "cwd": "cwd",
    "source": "source",  # SessionStart: startup
    "reason": "reason",  # SessionEnd: exit
    "message": "message",  # Notification
    "notification_type": "notification_type",  # Notification
}


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    """Map Claude external fields to internal schema.

    Drops fields like permission_mode, hook_event_name that we don't use.
    """
    _ = event_type  # Part of adapter interface
    return {internal: data[external] for external, internal in _CLAUDE_TO_INTERNAL.items() if external in data}
