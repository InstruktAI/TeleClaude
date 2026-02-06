"""User-facing error filtering and formatting."""

from __future__ import annotations

from teleclaude.core.events import ErrorEventContext

_HOOK_ERROR_MESSAGES: dict[str, str] = {
    "HOOK_INVALID_JSON": "Hook payload was invalid JSON. Re-run `telec init` and retry.",
    "HOOK_PAYLOAD_NOT_OBJECT": "Hook payload format was invalid. Re-run `telec init` and retry.",
    "HOOK_EVENT_DEPRECATED": "Hook event name is outdated. Re-run `telec init` to migrate hooks.",
}


def get_user_facing_error_message(context: ErrorEventContext) -> str | None:
    """Return a friendly error message for UI channels, or None to suppress.

    Internal/system errors should remain in logs and not be surfaced directly.
    """
    source = (context.source or "").strip()
    code = (context.code or "").strip()

    if source == "hook_receiver":
        if code in _HOOK_ERROR_MESSAGES:
            return _HOOK_ERROR_MESSAGES[code]
        if context.message:
            return f"Hook error: {context.message}"
        return "Hook error occurred."

    # Hide non-curated/system errors from user-facing channels.
    return None
