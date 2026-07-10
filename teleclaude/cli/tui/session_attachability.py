"""Session attachability helpers for TUI pane actions."""

from __future__ import annotations

NON_ATTACHABLE_SESSION_STATUSES = frozenset({"initializing", "closing", "escalated", "closed"})


def is_attachable_session(*, status: str, tmux_session_name: str | None) -> bool:
    """Return whether a session may open or focus a tmux pane."""
    return (
        bool(tmux_session_name) and not status.startswith("headless") and status not in NON_ATTACHABLE_SESSION_STATUSES
    )
