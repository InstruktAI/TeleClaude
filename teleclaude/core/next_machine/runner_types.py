"""Shared lifecycle runner value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RunnerLane(StrEnum):
    PREPARE = "prepare"
    WORK = "work"
    TASK_PREPARE = "task-prepare"
    TASK_RUN = "task-run"


class DispatchOrigin(StrEnum):
    """Who initiated a driver dispatch through the single dispatch primitive."""

    RUNNER = "runner"
    MANUAL = "manual"

    @property
    def manually_started(self) -> bool:
        return self is DispatchOrigin.MANUAL


class RunnerSkipReason(StrEnum):
    ADMISSION_UNAVAILABLE = "admission-unavailable"
    ALREADY_DRIVEN = "already-driven"
    APPROVAL_PENDING = "approval-pending"
    AT_CAPACITY = "at-capacity"
    DELIVERED = "delivered"
    DEPENDENCY_BLOCKED = "dependency-blocked"
    FINALIZE_READY = "finalize-ready"
    HELD = "held"
    ICEBOX = "icebox"
    INVALID_KIND = "invalid-kind"
    MISSING_STATE = "missing-state"
    POLICY_DISABLED = "policy-disabled"
    REMOVED = "removed"
    SCHEDULE_BLOCKED = "schedule-blocked"
    TASK_AUTHORIZATION_MISSING = "task-authorization-missing"
    UNKNOWN_PHASE = "unknown-phase"


class ManualLifecycleStatus(StrEnum):
    ADOPTED = "adopted"
    ALREADY_ACTIVE = "already-active"
    ALREADY_DRIVEN = "already-driven"
    DISPATCHED = "dispatched"
    NOT_BOUND = "not-bound"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class RunnerTodo:
    slug: str
    status: str
    kind: str | None
    lifecycle_phase: str | None
    human_approval_pending: bool
    hold: bool
    active_runner: str | None
    manually_started: bool = False
    after: tuple[str, ...] = ()
    schedule: str | None = None
    task_plan_digest: str = ""
    task_approved: bool = False
    task_approved_digest: str = ""
    plan_review_current: bool = False
    current_plan_digest: str = ""
    reviewed_plan_digest: str = ""
    dependency_drift_pending_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchIntent:
    slug: str
    lane: RunnerLane
    command: str
    additional_context: str


@dataclass
class RunnerDecision:
    evaluated: int = 0
    intents: list[DispatchIntent] = field(default_factory=list)
    skips: dict[RunnerSkipReason, list[str]] = field(default_factory=dict)

    def skip(self, reason: RunnerSkipReason, slug: str) -> None:
        self.skips.setdefault(reason, []).append(slug)


@dataclass
class RunnerResult:
    project_path: str
    trigger: str
    evaluated: int
    dispatched: list[DispatchIntent]
    skips: dict[RunnerSkipReason, list[str]]
    reconciled: list[str]


@dataclass(frozen=True)
class ManualLifecycleSessionResult:
    slug: str
    lane: RunnerLane
    status: ManualLifecycleStatus
    session_id: str | None = None
    reason: RunnerSkipReason | str | None = None
    work_feedback: str | None = None
