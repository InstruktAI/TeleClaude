"""Interpret a conversation's active maintenance attempt and idle-close markers.

The attempt identity and start time live in session platform metadata. The
provider-confirmed completion and real close remain session markers, so the idle
cycle and inbound delivery use the same definition of which attempt is live.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from teleclaude.core.models import Session
from teleclaude.core.session_compaction import (
    CompactionAttempt,
    CompactionStage,
    active_compaction_attempt,
    last_input_at,
)

CONVERSATION_IDLE_THRESHOLD: Final[timedelta] = timedelta(minutes=30)


def live_compaction_attempt(session: Session) -> CompactionAttempt | None:
    """The current maintenance attempt, unless accepted input superseded it."""
    attempt = active_compaction_attempt(session)
    if attempt is None:
        return None
    last_input = last_input_at(session)
    if last_input is not None and last_input > attempt.attempted_at:
        return None
    return attempt


def live_idle_close(session: Session) -> bool:
    """Whether the idle cycle closed the session and no input has reached it since.

    Input accepted for such a session resumes it; a session closed any other way, or one that
    took input after the idle close, does not.
    """
    closed = session.idle_closed_at
    if closed is None:
        return False
    last_input = last_input_at(session)
    return last_input is None or last_input <= closed


def compaction_completed(session: Session) -> bool:
    """Whether the live attempt has a provider completion stamped after it started."""
    attempt = live_compaction_attempt(session)
    completed = session.idle_compaction_completed_at
    return (
        attempt is not None
        and attempt.stage is not CompactionStage.RESTORING
        and completed is not None
        and completed > attempt.attempted_at
    )
