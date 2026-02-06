"""Claude hook adapter - normalizes Claude Code payloads to internal schema."""

from __future__ import annotations

from teleclaude.hooks.adapters.models import NormalizedHookPayload
from teleclaude.hooks.utils.parse_helpers import get_str


# guard: loose-dict-func - External hook payload is dynamic JSON from agent CLI.
def normalize_payload(event_type: str, data: dict[str, object]) -> NormalizedHookPayload:
    """Map Claude external fields to internal schema."""
    _ = event_type
    return NormalizedHookPayload(
        session_id=get_str(data, "session_id"),
        transcript_path=get_str(data, "transcript_path"),
        prompt=get_str(data, "prompt"),
        message=get_str(data, "message"),
    )
