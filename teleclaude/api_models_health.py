"""Liveness API DTOs with no config or storage dependencies."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from teleclaude.core.degradation import Degradation, DegradedComponent
from teleclaude.core.shutdown_drain import DrainObservation, DrainPhase


class PreparationObservationDTO(BaseModel):
    """The daemon's shutdown-preparation capability, process instance and phase.

    Liveness is not preparation evidence: a host caller reads this to learn that the
    running process supports preparation, which exact process instance it is, and
    whether that instance has drained.
    """

    model_config = ConfigDict(frozen=True)

    protocol: int
    pid: int
    token: str
    phase: DrainPhase
    held_units: int
    budget_seconds: float
    preparation_started_at: datetime | None = None
    held_labels: tuple[str, ...]
    termination_grace_seconds: float

    @classmethod
    def from_observation(cls, observation: DrainObservation) -> "PreparationObservationDTO":
        return cls(
            protocol=observation.protocol,
            pid=observation.pid,
            token=observation.token,
            phase=observation.phase,
            held_units=observation.held_units,
            budget_seconds=observation.budget_seconds,
            preparation_started_at=observation.preparation_started_at,
            held_labels=observation.held_labels,
            termination_grace_seconds=observation.termination_grace_seconds,
        )


class DegradationDTO(BaseModel):
    """One optional component, or one subject of it, that is not serving, why, and since when."""

    model_config = ConfigDict(frozen=True)

    component: DegradedComponent
    subject: str | None = None
    reason: str
    since: datetime

    @classmethod
    def from_degradation(cls, degradation: Degradation) -> "DegradationDTO":
        return cls(
            component=degradation.component,
            subject=degradation.subject,
            reason=degradation.reason,
            since=degradation.since,
        )


class HealthDTO(BaseModel):
    """Liveness of the daemon, the commit its code checkout stood on at start, and its preparation state.

    The preparation observation, the configuration migration reach (the newest configuration
    document version the process reads) and the optional components currently degraded are
    served on the local API socket only.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    start_commit: str | None = None
    preparation: PreparationObservationDTO | None = None
    config_migration_reach: int | None = None
    degraded: tuple[DegradationDTO, ...] | None = None
