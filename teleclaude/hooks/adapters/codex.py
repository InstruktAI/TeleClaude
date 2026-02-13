"""Codex hook adapter - normalizes Codex CLI notify payloads to internal schema."""

from __future__ import annotations

from teleclaude.hooks.adapters.models import NormalizedHookPayload
from teleclaude.hooks.utils.parse_helpers import get_str


# guard: loose-dict-func - External hook payload is dynamic JSON from agent CLI.
def normalize_payload(event_type: str, data: dict[str, object]) -> NormalizedHookPayload:
    """Map Codex notify fields to internal schema.

    Codex notify payload format:
    {
        "type": "agent-turn-complete",
        "thread-id": "019b7ea7-b98c-7431-bf04-ffc0dcd6eec4",
        "turn-id": "12345",
        "input-messages": ["user prompt"],
        "last-assistant-message": "assistant response"
    }

    Args:
        event_type: Event type (always "stop" for Codex notify)
        data: Raw Codex notify payload

    Returns:
        Normalized payload with session_id, transcript_path
    """
    _ = event_type  # Part of adapter interface

    # 1. Normalize: map external -> internal, drop unlisted fields
    session_id = get_str(data, "thread-id")
    prompt: str | None = None
    raw_prompt = data.get("input-messages")
    if isinstance(raw_prompt, list) and raw_prompt:
        prompt = str(raw_prompt[-1])
    elif isinstance(raw_prompt, str):
        prompt = raw_prompt

    # Codex prompt is a list of messages; take the last one as the current turn's prompt
    # Contract boundary: only trust payload fields here.
    transcript_path = get_str(data, "transcript_path")

    return NormalizedHookPayload(
        session_id=session_id,
        transcript_path=transcript_path,
        prompt=prompt,
    )
