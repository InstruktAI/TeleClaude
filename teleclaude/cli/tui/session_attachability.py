"""Session attachability helpers for TUI pane actions."""

from __future__ import annotations

from teleclaude.core.session_status import SessionLifecycleStatus


def is_attachable_session(*, status: str, tmux_session_name: str | None) -> bool:
    """Expose a bound pane independently of runtime startup and input readiness."""
    return (
        bool(tmux_session_name)
        and not status.startswith(SessionLifecycleStatus.HEADLESS)
        and status != SessionLifecycleStatus.CLOSED
    )
