"""The held standing a todo projection reports."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TodoStandingDTO(BaseModel):
    """The held standing of a ready item: ready at its commit, held by a session since a time, with the stated reasons."""

    model_config = ConfigDict(frozen=True)

    phase: str
    ready_at_commit: str
    ready_since: str
    held_by: str
    held_since: str
    reasons: list[str] = Field(default_factory=list)
