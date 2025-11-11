"""Session lifecycle event logging for debugging session deaths.

Writes JSON-formatted lifecycle events to a dedicated log file.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lifecycle log file path (in project root)
LIFECYCLE_LOG_PATH = Path.cwd() / "session_lifecycle.jsonl"


def log_lifecycle_event(
    event: str,
    session_id: str,
    tmux_session_name: Optional[str] = None,
    context: Optional[dict[str, object]] = None,
) -> None:
    """Log a session lifecycle event to JSON lines file.

    Args:
        event: Event type (session_created, polling_started, session_death_detected, etc.)
        session_id: Session ID
        tmux_session_name: Tmux session name (optional)
        context: Additional context (optional)
    """
    try:
        event_data: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "session_id": session_id[:8],  # Short ID for readability
        }

        if tmux_session_name:
            event_data["tmux"] = tmux_session_name

        if context:
            event_data["context"] = context

        # Append to JSON lines file
        with LIFECYCLE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_data) + "\n")

    except Exception as e:
        logger.warning("Failed to log lifecycle event: %s", e)


def log_session_created(session_id: str, tmux_session_name: str, title: str) -> None:
    """Log session creation event.

    Args:
        session_id: Session ID
        tmux_session_name: Tmux session name
        title: Session title
    """
    log_lifecycle_event(
        "session_created",
        session_id,
        tmux_session_name,
        {"title": title},
    )


def log_polling_started(session_id: str, tmux_session_name: str) -> None:
    """Log polling start event.

    Args:
        session_id: Session ID
        tmux_session_name: Tmux session name
    """
    log_lifecycle_event("polling_started", session_id, tmux_session_name)


def log_polling_ended(session_id: str, reason: str, context: Optional[dict[str, object]] = None) -> None:
    """Log polling end event.

    Args:
        session_id: Session ID
        reason: Reason for ending (exit_code, max_duration, session_death, etc.)
        context: Additional context (optional)
    """
    log_lifecycle_event("polling_ended", session_id, context={"reason": reason, **(context or {})})


def log_session_death(
    session_id: str,
    tmux_session_name: str,
    age_seconds: float,
    poll_count: int,
    context: Optional[dict[str, object]] = None,
) -> None:
    """Log unexpected session death event.

    Args:
        session_id: Session ID
        tmux_session_name: Tmux session name
        age_seconds: Session age in seconds
        poll_count: Number of polls before death
        context: Additional context (system metrics, etc.)
    """
    log_lifecycle_event(
        "session_death_detected",
        session_id,
        tmux_session_name,
        {
            "age_seconds": round(age_seconds, 2),
            "poll_count": poll_count,
            **(context or {}),
        },
    )


def log_session_closed(session_id: str, reason: str) -> None:
    """Log session closure event (normal shutdown).

    Args:
        session_id: Session ID
        reason: Reason for closure (user_command, exit, etc.)
    """
    log_lifecycle_event("session_closed", session_id, context={"reason": reason})
