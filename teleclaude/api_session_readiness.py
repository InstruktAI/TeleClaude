"""Shared additive readiness fields for session API DTOs."""

from pydantic import BaseModel


class SessionReadinessDTOFields(BaseModel):
    """Lifecycle evidence exposed by list and tail projections."""

    runtime_start_observed: bool = False
    runtime_activity_at: str | None = None
    lifecycle_transitioned_at: str | None = None
    lifecycle_transition_reason: str | None = None
    initializing_for_seconds: int | None = None
    attention: str | None = None
    procedure: str | None = None
