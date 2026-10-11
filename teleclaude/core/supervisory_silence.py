"""Describe when missing native signals meet the configured silence windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from teleclaude.config._models import AGENT_NO_SIGNAL_TIMEOUT_S, AGENT_NO_START_TIMEOUT_S
from teleclaude.core.session_status import AgentStatusValue


class SilenceObservationKind(StrEnum):
    """Native signal expected before one kind of silence observation."""

    STARTUP = "startup"
    ACTIVE_TURN = "active_turn"


class SilenceClock(StrEnum):
    """Timestamp source used to qualify an observation window."""

    LAST_SIGNAL = "last_signal"
    STATUS_ENTERED = "status_entered"


class SilenceTimeoutOwner(StrEnum):
    """Configuration field that owns one observation window."""

    STARTUP = "AGENT_NO_START_TIMEOUT_S"
    ACTIVE_TURN = "AGENT_NO_SIGNAL_TIMEOUT_S"


@dataclass(frozen=True)
class SilenceRule:
    """Clock and native-evidence conditions for one silence observation."""

    kind: SilenceObservationKind
    status: AgentStatusValue
    window_s: float
    silence_clock: SilenceClock
    timeout_owner: SilenceTimeoutOwner
    tool_calls_must_be_closed: bool
    agent_must_be_assigned: bool


@dataclass(frozen=True)
class SilenceObservation:
    """Bounded evidence for a missing native signal, addressed to a supervisor."""

    target_session_id: str
    target_computer: str
    runtime: str | None
    run_id: str | None
    turn_id: str | None
    kind: SilenceObservationKind
    observed_at: datetime | None
    clock_evidence_at: datetime | None
    window_s: float | None
    silence_clock: SilenceClock
    timeout_owner: SilenceTimeoutOwner | None
    pane_tail: str | None
    pane_available: bool
    inspection_reference: str
    legacy_window_label: str | None = None


@dataclass(frozen=True)
class SilenceClaim:
    """Persisted claim identity and clock evidence for one observation."""

    target_session_id: str
    run_id: str
    turn_id: str | None
    kind: SilenceObservationKind
    observed_at: datetime
    clock_evidence_at: datetime


SILENCE_RULES = (
    SilenceRule(
        kind=SilenceObservationKind.ACTIVE_TURN,
        status=AgentStatusValue.ACTIVE,
        window_s=AGENT_NO_SIGNAL_TIMEOUT_S,
        silence_clock=SilenceClock.LAST_SIGNAL,
        timeout_owner=SilenceTimeoutOwner.ACTIVE_TURN,
        tool_calls_must_be_closed=True,
        agent_must_be_assigned=False,
    ),
    SilenceRule(
        kind=SilenceObservationKind.STARTUP,
        status=AgentStatusValue.UNKNOWN,
        window_s=AGENT_NO_START_TIMEOUT_S,
        silence_clock=SilenceClock.STATUS_ENTERED,
        timeout_owner=SilenceTimeoutOwner.STARTUP,
        tool_calls_must_be_closed=False,
        agent_must_be_assigned=True,
    ),
)
