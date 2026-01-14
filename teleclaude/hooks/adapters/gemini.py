"""Gemini hook adapter - normalizes Gemini CLI payloads to internal schema."""

from __future__ import annotations

# Explicit mapping: Gemini external field -> internal field
# Only these fields are forwarded; everything else (llm_request, tool_input, etc.) is dropped
_GEMINI_TO_INTERNAL: dict[str, str] = {
    "session_id": "session_id",
    "transcript_path": "transcript_path",
    "cwd": "cwd",
    "timestamp": "timestamp",
    "prompt": "prompt",  # BeforeAgent / AfterAgent
    "prompt_response": "prompt_response",  # AfterAgent
    "source": "source",  # SessionStart: startup|resume|clear
    "reason": "reason",  # SessionEnd: exit|clear|logout|prompt_input_exit|other
    "message": "message",  # Notification
    "notification_type": "notification_type",  # Notification
    "details": "details",  # Notification
}


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:  # noqa: loose-dict - Agent hook boundary
    """Map Gemini external fields to internal schema.

    Drops large fields like llm_request, llm_response, tool_input, tool_output
    that cause MCP timeout issues due to payload size.
    """
    _ = event_type  # Part of adapter interface

    # Normalize: map external -> internal, drop unlisted fields
    return {internal: data[external] for external, internal in _GEMINI_TO_INTERNAL.items() if external in data}
