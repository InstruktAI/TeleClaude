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
    from instrukt_ai_logging import get_logger

    logger = get_logger(__name__)

    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        logger.debug(
            "Codex sessions directory not found",
            sessions_dir=str(sessions_dir),
        )
        return ""

    # Search for session file matching session_id suffix
    # Start from today and work backwards (most likely to find recent sessions)
    today = datetime.now()
    for days_back in range(7):  # Search last 7 days
        try:
            check_date = today - timedelta(days=days_back) if days_back > 0 else today
            date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
            if date_dir.exists():
                for session_file in date_dir.glob(f"rollout-*-{session_id}.jsonl"):
                    logger.debug(
                        "Codex transcript discovered",
                        session_id=session_id,
                        path=str(session_file),
                    )
                    return str(session_file)
        except (ValueError, OSError) as e:
            logger.debug(
                "Error searching Codex date directory",
                days_back=days_back,
                error=str(e),
            )
            continue

    # Fallback: search all directories
    logger.debug("Falling back to recursive Codex search", session_id=session_id)
    for session_file in sessions_dir.rglob(f"rollout-*-{session_id}.jsonl"):
        logger.debug(
            "Codex transcript discovered (recursive)",
            session_id=session_id,
            path=str(session_file),
        )
        return str(session_file)

    logger.warning(
        "Codex transcript not found",
        session_id=session_id,
        search_dirs=[
            str(
                sessions_dir
                / f"{(today - timedelta(days=i)).year}"
                / f"{(today - timedelta(days=i)).month:02d}"
                / f"{(today - timedelta(days=i)).day:02d}"
            )
            for i in range(7)
        ],
    )
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
