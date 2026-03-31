"""Shared session status derivation rules."""

from __future__ import annotations

from datetime import datetime


def compute_agent_status(
    *,
    last_activity: datetime | None,
    last_agent_stop_at: datetime | None,
) -> str:
    """Derive session activity status from observed activity timestamps."""
    if not isinstance(last_activity, datetime):
        return "unknown"
    if isinstance(last_agent_stop_at, datetime) and last_agent_stop_at == last_activity:
        return "idle"
    return "active"
