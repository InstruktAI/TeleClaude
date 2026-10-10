"""What a session's idle-cycle stamps say: whether a compaction was asked for, whether it completed, and the close.

A conversation session's idle cycle (``teleclaude.core.idle_close``) stamps the
moment it asked the agent to compact and the moment it closed the session; the
agent-idle handler stamps the moment the agent reported that compaction complete.
They and the inbound delivery read the stamps through this module, so none of them
can disagree about which request or close is live.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from teleclaude.core.models import Session

CONVERSATION_IDLE_THRESHOLD: Final[timedelta] = timedelta(minutes=30)


def last_input_at(session: Session) -> datetime | None:
    """When the session last received input; a session that never did dates from its creation."""
    return session.last_message_sent_at or session.created_at


def live_compaction_request(session: Session) -> datetime | None:
    """The moment the cycle asked for a compaction, unless input arrived after it and voided the request."""
    requested = session.idle_compaction_requested_at
    if requested is None:
        return None
    last_input = last_input_at(session)
    if last_input is not None and last_input > requested:
        return None
    return requested


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
    """Whether the live compaction request has a completion stamped after it."""
    requested = live_compaction_request(session)
    completed = session.idle_compaction_completed_at
    return requested is not None and completed is not None and completed > requested
