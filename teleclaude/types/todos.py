"""Pydantic models for Todo state management."""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class DorActions(BaseModel):
    """Actions taken during DOR assessment."""

    model_config = ConfigDict(extra="allow")
    requirements_updated: bool = False
    implementation_plan_updated: bool = False


class DorState(BaseModel):
    """Definition of Ready (DOR) assessment state."""

    last_assessed_at: Optional[str] = None
    score: int = 0
    status: str = "needs_work"  # pass, needs_work, needs_decision
    schema_version: int = 1
    blockers: list[str] = Field(default_factory=list)
    actions_taken: Union[DorActions, list[str]] = Field(default_factory=DorActions)


class BreakdownState(BaseModel):
    """Breakdown assessment state for complex todos."""

    assessed: bool = False
    todos: list[str] = Field(default_factory=list)


class TodoState(BaseModel):
    """Canonical state for a TeleClaude work item."""

    build: str = "pending"
    review: str = "pending"
    deferrals_processed: bool = False
    breakdown: BreakdownState = Field(default_factory=BreakdownState)
    dor: Optional[DorState] = None
    review_round: int = 0
    max_review_rounds: int = 3
    review_baseline_commit: str = ""
    unresolved_findings: list[str] = Field(default_factory=list)
    resolved_findings: list[str] = Field(default_factory=list)
    schema_version: int = 1
