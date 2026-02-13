"""Codex transcript discovery helpers.

Core-owned utility for resolving Codex native transcript paths.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def discover_codex_transcript_path(native_session_id: str) -> str | None:
    """Resolve Codex transcript path for a native session id.

    Codex stores transcripts in:
    ~/.codex/sessions/YYYY/MM/DD/rollout-*-{native_session_id}.jsonl
    """
    if not native_session_id:
        return None

    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        logger.debug(
            "Codex sessions directory not found",
            sessions_dir=str(sessions_dir),
        )
        return None

    today = datetime.now()
    for days_back in range(7):
        try:
            check_date = today - timedelta(days=days_back)
            date_dir = sessions_dir / f"{check_date.year}" / f"{check_date.month:02d}" / f"{check_date.day:02d}"
            if not date_dir.exists():
                continue
            for transcript_file in date_dir.glob(f"rollout-*-{native_session_id}.jsonl"):
                logger.debug(
                    "Codex transcript discovered",
                    native_session_id=native_session_id,
                    path=str(transcript_file),
                )
                return str(transcript_file)
        except (ValueError, OSError) as exc:
            logger.debug(
                "Codex transcript date scan error",
                days_back=days_back,
                error=str(exc),
            )

    logger.debug("Falling back to recursive Codex transcript search", native_session_id=native_session_id)
    for transcript_file in sessions_dir.rglob(f"rollout-*-{native_session_id}.jsonl"):
        logger.debug(
            "Codex transcript discovered (recursive)",
            native_session_id=native_session_id,
            path=str(transcript_file),
        )
        return str(transcript_file)

    logger.warning("Codex transcript not found", native_session_id=native_session_id)
    return None
