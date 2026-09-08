"""Availability state and launch eligibility for agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from teleclaude.core.dates import parse_iso_datetime


class AgentAvailabilityStatus(StrEnum):
    """Closed operator-availability states for agents and declared models."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class LaunchOwnership(StrEnum):
    """The launch intent that decides whether degraded capacity is usable."""

    HUMAN = "human"
    JOB_ROLE = "job_role"


def launch_ownership(job_role: str | None) -> LaunchOwnership:
    """Classify persisted job-role presence into model-launch ownership."""
    return LaunchOwnership.JOB_ROLE if job_role else LaunchOwnership.HUMAN


@dataclass(frozen=True)
class AvailabilityState:
    """One availability subject's status, optional expiry, and operator reason."""

    status: AgentAvailabilityStatus
    status_until: str | None
    reason: str | None

    def normalized(self, now: datetime) -> AvailabilityState:
        """Return the available state when this state has expired."""
        until = parse_iso_datetime(self.status_until)
        if until is not None and until < now:
            return AvailabilityState(AgentAvailabilityStatus.AVAILABLE, None, None)
        return self


def is_launchable(status: AgentAvailabilityStatus, ownership: LaunchOwnership) -> bool:
    """Return whether one launch owner may use capacity in this status."""
    match status:
        case AgentAvailabilityStatus.AVAILABLE:
            return True
        case AgentAvailabilityStatus.DEGRADED:
            return ownership is LaunchOwnership.HUMAN
        case AgentAvailabilityStatus.UNAVAILABLE:
            return False
