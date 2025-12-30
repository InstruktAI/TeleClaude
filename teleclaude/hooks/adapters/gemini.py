"""Gemini hook adapter - normalizes Gemini CLI payloads to internal schema."""

from __future__ import annotations

import hashlib
from pathlib import Path

# Explicit mapping: Gemini external field -> internal field
# Only these fields are forwarded; everything else (llm_request, tool_input, etc.) is dropped
_GEMINI_TO_INTERNAL: dict[str, str] = {
    "session_id": "session_id",
    "transcript_path": "transcript_path",
    "cwd": "cwd",
    "timestamp": "timestamp",
    "source": "source",  # SessionStart: startup|resume|clear
    "reason": "reason",  # SessionEnd: exit|clear|logout|prompt_input_exit|other
    "message": "message",  # Notification
    "notification_type": "notification_type",  # Notification
    "details": "details",  # Notification
}


def _discover_transcript_path(data: dict[str, object]) -> str:
    """Discover Gemini transcript path when not provided in payload.

    Gemini stores transcripts at:
    ~/.gemini/tmp/{sha256(cwd)}/chats/session-{date}-{session_id[:8]}.json

    This fallback is needed because Gemini CLI doesn't always populate
    transcript_path in hook events.
    See: https://github.com/google-gemini/gemini-cli/issues/14715
    """
    cwd = data.get("cwd")
    session_id = data.get("session_id")
    if not isinstance(cwd, str) or not isinstance(session_id, str):
        return ""

    # Compute project hash from cwd
    project_hash = hashlib.sha256(cwd.encode()).hexdigest()
    chats_dir = Path.home() / ".gemini" / "tmp" / project_hash / "chats"

    if not chats_dir.exists():
        return ""

    # Search for session file matching session_id prefix
    session_prefix = session_id[:8]
    for session_file in chats_dir.glob(f"session-*-{session_prefix}.json"):
        return str(session_file)

    return ""


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    """Map Gemini external fields to internal schema.

    Drops large fields like llm_request, llm_response, tool_input, tool_output
    that cause MCP timeout issues due to payload size.

    Enriches with transcript_path if not provided by Gemini CLI.
    """
    _ = event_type  # Part of adapter interface

    # 1. Normalize: map external -> internal, drop unlisted fields
    result = {internal: data[external] for external, internal in _GEMINI_TO_INTERNAL.items() if external in data}

    # 2. Enrich: discover transcript_path if not provided
    if not result.get("transcript_path"):
        discovered = _discover_transcript_path(data)
        if discovered:
            result["transcript_path"] = discovered

    return result
