"""Claude hook adapter - normalizes Claude Code payloads to internal schema."""

from __future__ import annotations

from typing import Any, Mapping

from teleclaude.hooks.adapters.models import NormalizedHookPayload
from teleclaude.hooks.utils.parse_helpers import get_str


def normalize_payload(event_type: str, data: Mapping[str, Any]) -> NormalizedHookPayload:
    """Map Claude external fields to internal schema."""
    _ = event_type  # Part of adapter interface
    return NormalizedHookPayload(
        session_id=get_str(data, "session_id"),
        transcript_path=get_str(data, "transcript_path"),
        prompt=get_str(data, "user_prompt"),
        message=get_str(data, "message"),
    )
