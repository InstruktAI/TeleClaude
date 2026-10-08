"""Liveness API DTOs with no config or storage dependencies."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

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

    @classmethod
    def from_observation(cls, observation: DrainObservation) -> "PreparationObservationDTO":
        return cls(
            protocol=observation.protocol,
            pid=observation.pid,
            token=observation.token,
            phase=observation.phase,
            held_units=observation.held_units,
            budget_seconds=observation.budget_seconds,
        )


class HealthDTO(BaseModel):
    """Liveness of the daemon, the commit its code checkout stood on at start, and its preparation state.

    The preparation observation is served on the local API socket only.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    start_commit: str | None = None
    preparation: PreparationObservationDTO | None = None
