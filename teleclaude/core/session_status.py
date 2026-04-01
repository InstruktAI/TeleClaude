"""Shared session status derivation rules."""

from __future__ import annotations

from datetime import datetime


def compute_agent_status(
    *,
    last_activity: datetime | None,
    last_input_at: datetime | None,
    last_agent_stop_at: datetime | None,
) -> str:
    """Derive session activity status from observed activity timestamps.

    The stop event is authoritative: once fired, the agent is idle unless
    new input arrived after the stop (indicating a new turn started).
    Poller flushes that bump last_activity after the stop are not signal.
    """
    if not isinstance(last_activity, datetime):
        return "unknown"
    if isinstance(last_agent_stop_at, datetime):
        if not isinstance(last_input_at, datetime) or last_input_at <= last_agent_stop_at:
            return "idle"
    return "active"
