"""Shared session status derivation rules."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from teleclaude.config._models import STALL_THRESHOLD_SECONDS

TERMINAL_LIFECYCLE_STATUSES = frozenset({"closing", "closed"})


class AgentStatusValue(StrEnum):
    """Canonical projection values for an agent session's activity state."""

    ACTIVE = "active"
    IDLE = "idle"
    STALLED = "stalled"
    UNKNOWN = "unknown"


def is_session_open(*, closed_at: datetime | None) -> bool:
    """Return whether a session remains part of the open-session set.

    ``closed_at`` is the sole visibility boundary. Lifecycle status describes
    what an open session is doing; it never silently removes that session from
    listings or projections.
    """
    return closed_at is None


def is_session_terminal(*, lifecycle_status: str | None, closed_at: datetime | None) -> bool:
    """Return whether a session rejects further runtime interaction."""
    return not is_session_open(closed_at=closed_at) or lifecycle_status in TERMINAL_LIFECYCLE_STATUSES


def compute_agent_status(
    *,
    lifecycle_status: str | None,
    closed_at: datetime | None,
    last_activity: datetime | None,
    last_input_at: datetime | None,
    last_agent_stop_at: datetime | None,
    now: datetime,
) -> AgentStatusValue:
    """Derive session activity status from lifecycle and observed timestamps.

    Terminal lifecycle markers are authoritative over activity timestamps.
    The stop event is authoritative: once fired, the agent is idle unless
    new input arrived after the stop (indicating a new turn started).
    Poller flushes that bump last_activity after the stop are not signal.
    """
    if is_session_terminal(lifecycle_status=lifecycle_status, closed_at=closed_at):
        return AgentStatusValue.IDLE
    if not isinstance(last_activity, datetime):
        return AgentStatusValue.UNKNOWN
    if isinstance(last_agent_stop_at, datetime):
        if not isinstance(last_input_at, datetime) or last_input_at <= last_agent_stop_at:
            return AgentStatusValue.IDLE
        if (now - last_activity).total_seconds() > STALL_THRESHOLD_SECONDS:
            return AgentStatusValue.STALLED
    return AgentStatusValue.ACTIVE
