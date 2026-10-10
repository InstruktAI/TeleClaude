"""Shared session status derivation rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.core.models import SessionSnapshot


class SessionLifecycleStatus(StrEnum):
    """Closed vocabulary for a session's lifecycle status field.

    Two distinct questions read this vocabulary and split on ``CLOSING``.
    For runtime interaction it is terminal — a closing session rejects input,
    so ``TERMINAL_LIFECYCLE_STATUSES`` includes it. For finality it is not:
    the close is in flight and a failed close restores the session, so state
    tied to the session's existence is released only on ``CLOSED``. Reference
    members instead of inlining the strings.
    """

    ACTIVE = "active"
    HEADLESS = "headless"
    INITIALIZING = "initializing"
    ESCALATED = "escalated"
    CLOSING = "closing"
    CLOSED = "closed"


class HostPaneViewerAdmission(StrEnum):
    """Whether a session currently admits a newly-created host viewer."""

    ADMITTED = "admitted"
    UNAVAILABLE = "unavailable"


class SessionSelectionDisposition(StrEnum):
    """Runtime-owned action available to an ordinary session-row selection."""

    PREVIEW = "preview"
    ADOPT_HEADLESS = "adopt_headless"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HostPaneAccessProjection:
    """Current fresh-viewer admission and normal row-selection disposition."""

    viewer_admission: HostPaneViewerAdmission
    selection: SessionSelectionDisposition


def project_host_pane_access(session: SessionSnapshot) -> HostPaneAccessProjection:
    """Project fresh attachment and row-selection access from session-owned facts."""
    status = session.status
    has_open_row = session.closed_at is None and status != SessionLifecycleStatus.CLOSED
    has_bound_host = bool(session.tmux_session_name)

    if not has_open_row:
        return HostPaneAccessProjection(
            viewer_admission=HostPaneViewerAdmission.UNAVAILABLE,
            selection=SessionSelectionDisposition.UNAVAILABLE,
        )

    if status == SessionLifecycleStatus.HEADLESS and not has_bound_host:
        return HostPaneAccessProjection(
            viewer_admission=HostPaneViewerAdmission.UNAVAILABLE,
            selection=SessionSelectionDisposition.ADOPT_HEADLESS,
        )

    if status != SessionLifecycleStatus.HEADLESS and has_bound_host:
        return HostPaneAccessProjection(
            viewer_admission=HostPaneViewerAdmission.ADMITTED,
            selection=SessionSelectionDisposition.PREVIEW,
        )

    return HostPaneAccessProjection(
        viewer_admission=HostPaneViewerAdmission.UNAVAILABLE,
        selection=SessionSelectionDisposition.UNAVAILABLE,
    )


TERMINAL_LIFECYCLE_STATUSES = frozenset({SessionLifecycleStatus.CLOSING, SessionLifecycleStatus.CLOSED})


class AgentStatusValue(StrEnum):
    """Canonical projection values for an agent session's activity state."""

    ACTIVE = "active"
    IDLE = "idle"
    BLOCKED = "blocked"
    STALLED = "stalled"
    UNKNOWN = "unknown"


class AgentStatusReason(StrEnum):
    """Structured reasons for a non-idle agent status."""

    NEEDS_INPUT = "needs_input"
    QUOTA_WAIT = "quota_wait"
    TURN_FAILED = "turn_failed"
    NO_SIGNAL = "no_signal"
    NO_START = "no_start"


class TurnNotificationRecord(StrEnum):
    """Notification outcomes recorded for the current session turn."""

    TERMINAL_TURN_END = "terminal_turn_end"
    TERMINAL_TURN_FAILED = "terminal_turn_failed"
    BLOCKED = "blocked"
    INFERRED_STALL = "inferred_stall"


TERMINAL_NOTIFICATION_RECORDS: frozenset[TurnNotificationRecord] = frozenset(
    {TurnNotificationRecord.TERMINAL_TURN_END, TurnNotificationRecord.TERMINAL_TURN_FAILED}
)


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


def is_close_started(*, lifecycle_status: str | None) -> bool:
    """Return whether a session's close has already been declared started.

    ``closed_at`` answers whether the close is *finished*; this answers
    whether it has *started*. The two diverge for a session stranded at
    ``CLOSING`` with no ``closed_at`` marker — an interrupted close.
    """
    return lifecycle_status == SessionLifecycleStatus.CLOSING


def is_agent_turn_running(
    *,
    last_input_at: datetime | None,
    last_agent_stop_at: datetime | None,
    last_agent_idle_at: datetime | None,
) -> bool:
    """Return whether accepted input is later than every authoritative idle boundary."""
    if not isinstance(last_input_at, datetime):
        return False
    idle_boundaries = [
        boundary for boundary in (last_agent_stop_at, last_agent_idle_at) if isinstance(boundary, datetime)
    ]
    return not idle_boundaries or last_input_at > max(idle_boundaries)
