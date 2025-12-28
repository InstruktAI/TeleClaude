"""Gemini hook adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _find_transcript_path(data: dict[str, object]) -> str:
    """Find Gemini transcript path based on cwd and session_id.

    Gemini stores transcripts at:
    ~/.gemini/tmp/{sha256(cwd)}/chats/session-{date}-{session_id[:8]}.json

    TODO: Remove this workaround once Gemini CLI properly populates transcript_path
    in hook events. See https://github.com/google-gemini/gemini-cli/issues/14715
    The transcript_path field is already passed in some events - this fallback
    discovery may be unnecessary.
    """
    # If transcript_path is already provided and valid, use it
    existing = data.get("transcript_path")
    if isinstance(existing, str) and existing:
        return existing

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


def _enrich_transcript_path(data: dict[str, object]) -> dict[str, object]:
    """Enrich data with transcript_path if not already set."""
    result = dict(data)
    transcript_path = _find_transcript_path(data)
    if transcript_path:
        result["transcript_path"] = transcript_path
    return result


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    """Normalize Gemini hook payload - enrich ALL events with transcript_path."""
    # All events get enriched - unknown events often arrive first with transcript_path
    _ = event_type  # unused but part of adapter interface
    return _enrich_transcript_path(data)
