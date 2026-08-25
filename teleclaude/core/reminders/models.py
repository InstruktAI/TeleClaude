"""Typed reminder aggregate and source-entry models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite

from teleclaude.core.dates import ensure_utc

_POSITIVE_AFTER_ERROR = "after_seconds must be finite and positive"
_POSITIVE_INTERVAL_ERROR = "interval_seconds must be finite and positive"


class ReminderTrigger(StrEnum):
    """Supported reminder activation mechanisms."""

    TIME = "time"
    AGENT_EVENT = "agent_event"


class ReminderRecurrence(StrEnum):
    """Supported recurrence modes."""

    ONE_SHOT = "one_shot"
    RECURRING = "recurring"


class ReminderTransition(StrEnum):
    """Material reminder lifecycle transitions."""

    ARMED = "armed"
    REPLACED = "replaced"
    CANCELLED = "cancelled"
    FIRING = "firing"


class ReminderCancelReason(StrEnum):
    """Closed reasons recorded on reminder cancellation entries."""

    AUTO_CANCEL_NOOP = "auto_cancel_noop"


class ReminderAutoCancelOutcome(StrEnum):
    """Closed outcomes for a pending firing-answer evaluation."""

    CANCELLED = "cancelled"
    ANSWERED = "answered"
    UNRESOLVED = "unresolved"


class ReminderSubmissionPath(StrEnum):
    """Accepted delivery paths for a firing submitted to inbound."""

    FRESH = "fresh"
    DUPLICATE_BOUND = "duplicate_bound"
    DUPLICATE_UNBOUND = "duplicate_unbound"


class ReminderEventAnchor(StrEnum):
    """Typed agent events that can activate a reminder."""

    AGENT_STOP = "agent_stop"


class PrescribedReminderSlug(StrEnum):
    """Reserved reminder slugs with registered formatters."""

    GOAL_DRIVE = "goal-drive"
    SESSION_DEPARTURE = "session-departure"
    ORCHESTRATION_WATCH = "orchestration-watch"
    COORDINATOR_SWEEP = "coordinator-sweep"
    INTEGRATOR_MAIN_CLEARANCE = "integrator-main-clearance"
    INTEGRATOR_CANDIDATE_SETTLEDNESS = "integrator-candidate-settledness"


@dataclass(frozen=True)
class ReminderSchedule:
    """Validated schedule for a reminder generation."""

    trigger: ReminderTrigger
    recurrence: ReminderRecurrence
    next_fire_at: datetime | None = None
    interval_seconds: float | None = None
    event_anchor: ReminderEventAnchor | None = None

    def __post_init__(self) -> None:
        if self.trigger is ReminderTrigger.TIME:
            if self.next_fire_at is None:
                raise ValueError("time reminders require next_fire_at")
            if self.event_anchor is not None:
                raise ValueError("time reminders cannot carry an event anchor")
            if self.recurrence is ReminderRecurrence.RECURRING and self.interval_seconds is None:
                raise ValueError("recurring reminders require interval_seconds")
        elif self.event_anchor is None:
            raise ValueError("event reminders require an event anchor")
        elif self.next_fire_at is not None or self.interval_seconds is not None:
            raise ValueError("event reminders cannot carry time scheduling fields")
        if self.interval_seconds is not None and (not isfinite(self.interval_seconds) or self.interval_seconds <= 0):
            raise ValueError(_POSITIVE_INTERVAL_ERROR)

    @classmethod
    def relative(cls, *, after_seconds: float, repeat: bool, now: datetime | None = None) -> ReminderSchedule:
        """Create a relative schedule from a positive duration."""
        if not isfinite(after_seconds) or after_seconds <= 0:
            raise ValueError(_POSITIVE_AFTER_ERROR)
        armed_at = ensure_utc(now or datetime.now(UTC))
        recurrence = ReminderRecurrence.RECURRING if repeat else ReminderRecurrence.ONE_SHOT
        return cls(
            trigger=ReminderTrigger.TIME,
            recurrence=recurrence,
            next_fire_at=armed_at + timedelta(seconds=after_seconds),
            interval_seconds=after_seconds if repeat else None,
        )

    @classmethod
    def absolute(cls, *, at: datetime) -> ReminderSchedule:
        """Create an absolute one-shot schedule."""
        return cls(
            trigger=ReminderTrigger.TIME,
            recurrence=ReminderRecurrence.ONE_SHOT,
            next_fire_at=ensure_utc(at),
        )

    @classmethod
    def on_event(cls, anchor: ReminderEventAnchor) -> ReminderSchedule:
        """Create an event-anchored one-shot schedule."""
        return cls(
            trigger=ReminderTrigger.AGENT_EVENT,
            recurrence=ReminderRecurrence.ONE_SHOT,
            event_anchor=anchor,
        )


@dataclass(frozen=True)
class Reminder:
    """Current durable reminder aggregate generation."""

    session_id: str
    slug: str
    profile: PrescribedReminderSlug | None
    intent: str
    schedule: ReminderSchedule
    armed_at: datetime
    generation: int
    occurrence_key: str
    sliding: bool = False
    auto_cancel: bool = False
    pending_answer_occurrence_key: str | None = None
    pending_answer_inbound_id: int | None = None
    pending_answer_at: datetime | None = None
    claimed_occurrence_key: str | None = None
    claimed_at: datetime | None = None


@dataclass(frozen=True)
class ReminderEntry:
    """Append-only material reminder transition."""

    entry_id: int
    session_id: str
    slug: str
    generation: int
    transition: ReminderTransition
    profile: str | None
    intent: str
    schedule: ReminderSchedule
    armed_at: datetime
    occurred_at: datetime
    occurrence_key: str
    sliding: bool = False
    auto_cancel: bool = False
    cancel_reason: ReminderCancelReason | None = None


@dataclass(frozen=True)
class ReminderEntryReadFailure:
    """Permanent record-local failure while reading one immutable reminder entry."""

    entry_id: int
    session_id: str
    occurred_at: datetime | None
    reason: str


type ReminderEntryReadItem = ReminderEntry | ReminderEntryReadFailure


@dataclass(frozen=True)
class ReminderSubmissionResult:
    """Accepted inbound submission with optional durable row identity."""

    acceptance_path: ReminderSubmissionPath
    inbound_queue_id: int | None


@dataclass(frozen=True)
class ReminderSetRequest:
    """Core set command after edge validation and profile formatting."""

    session_id: str
    slug: str
    intent: str
    schedule: ReminderSchedule
    profile: PrescribedReminderSlug | None = None
    sliding: bool = False
    auto_cancel: bool = False


@dataclass(frozen=True)
class ReminderEvent:
    """Normalized agent event fact consumed by reminder predicates."""

    session_id: str
    event_id: str
    anchor: ReminderEventAnchor
