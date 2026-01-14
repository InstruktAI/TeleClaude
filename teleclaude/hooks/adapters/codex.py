"""Codex hook adapter - normalizes Codex CLI notify payloads to internal schema."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from teleclaude.hooks.adapters.models import NormalizedHookPayload
from teleclaude.hooks.utils.parse_helpers import get_str


def _discover_transcript_path(session_id: str) -> str:
    """Discover Codex transcript path from session ID.

    Codex stores transcripts at:
    ~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{session_id}.jsonl

    Args:
        session_id: Codex native session ID (thread-id from notify payload)

    Returns:
        Path to transcript file if found, empty string otherwise
    """
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return ""

    # Search for session file matching session_id suffix
    # Start from today and work backwards (most likely to find recent sessions)
    today = datetime.now()
    for days_back in range(7):  # Search last 7 days
        check_date = today.replace(day=today.day - days_back) if days_back == 0 else today
        try:
            if days_back > 0:
                check_date = today - timedelta(days=days_back)
            date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
            if date_dir.exists():
                for session_file in date_dir.glob(f"rollout-*-{session_id}.jsonl"):
                    return str(session_file)
        except (ValueError, OSError):
            continue

    # Fallback: search all directories
    for session_file in sessions_dir.rglob(f"rollout-*-{session_id}.jsonl"):
        return str(session_file)

    return ""


def normalize_payload(event_type: str, data: Mapping[str, Any]) -> NormalizedHookPayload:
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
    # 2. Enrich: discover transcript_path from session_id
    transcript_path = _discover_transcript_path(session_id) if session_id else ""

    return NormalizedHookPayload(
        session_id=session_id,
        transcript_path=transcript_path or None,
        prompt=prompt,
    )
