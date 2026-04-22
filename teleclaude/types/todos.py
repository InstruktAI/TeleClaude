"""Pydantic models for Todo state management (schema v1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teleclaude.types.state_value import StateValue


class DorActions(BaseModel):
    """Actions taken during DOR assessment."""

    model_config = ConfigDict(extra="allow")
    requirements_updated: bool = False
    implementation_plan_updated: bool = False


class DorState(BaseModel):
    """Definition of Ready (DOR) assessment state."""

    last_assessed_at: str | None = None
    score: int = 0
    status: str = "needs_work"  # pass, needs_work, needs_decision
    schema_version: int = 1
    blockers: list[str] = Field(default_factory=list)
    actions_taken: DorActions | list[str] = Field(default_factory=DorActions)


class BreakdownState(BaseModel):
    """Breakdown assessment state for complex todos."""

    assessed: bool = False
    todos: list[str] = Field(default_factory=list)


class FinalizeModel(BaseModel):
    """Finalize phase state."""

    status: str = "pending"
    branch: str = ""
    sha: str = ""
    ready_at: str = ""
    handed_off_at: str = ""


class GroundingState(BaseModel):
    """Grounding / freshness state."""

    valid: bool = False
    base_sha: str = ""
    input_digest: str = ""
    referenced_paths: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)
    last_grounded_at: str = ""
    invalidated_at: str = ""
    invalidation_reason: str = ""


class ReviewFinding(BaseModel):
    """Structured record for a single review finding."""

    model_config = ConfigDict(extra="allow")
    id: str = ""
    severity: str = ""
    summary: str = ""
    status: str = "open"
    resolved_at: str = ""
    resolution_method: str = ""


class ReviewVerdictState(BaseModel):
    """Verdict state for a prepare review phase."""

    verdict: str = ""
    reviewed_at: str = ""
    findings_count: int = 0
    rounds: int = 0
    baseline_commit: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)


class TestSpecReviewState(BaseModel):
    """Verdict state for test spec review (no baseline_commit/findings)."""

    verdict: str = ""
    reviewed_at: str = ""
    findings_count: int = 0
    rounds: int = 0


class BuildReviewState(BaseModel):
    """Verdict state for the work (build) review phase.

    Unlike prepare reviews, the build review tracks a baseline_commit so that
    re-review dispatch can restrict diff scope to commits since the last
    verdict. ``round`` increments on every ``changes_requested`` verdict.
    """

    verdict: str = ""
    reviewed_at: str = ""
    round: int = 0
    baseline_commit: str = ""
    dispatch_head: str = ""


class Event(BaseModel):
    """Audit log entry for a state transition or stamp side-effect."""

    at: str
    actor: str
    kind: str
    details: dict[str, StateValue] = Field(default_factory=dict)


class ArtifactEntry(BaseModel):
    """Lifecycle stamp for a single artifact."""

    digest: str = ""
    produced_at: str = ""
    stale: bool = False
    approved: bool = False
    confirmed: bool = False


class ArtifactsState(BaseModel):
    """Artifact lifecycle stamps."""

    input: ArtifactEntry = Field(default_factory=ArtifactEntry)
    requirements: ArtifactEntry = Field(default_factory=ArtifactEntry)
    test_specs: ArtifactEntry = Field(default_factory=ArtifactEntry)
    implementation_plan: ArtifactEntry = Field(default_factory=ArtifactEntry)
    art: ArtifactEntry = Field(default_factory=ArtifactEntry)
    visuals: ArtifactEntry = Field(default_factory=ArtifactEntry)
    design_spec: ArtifactEntry = Field(default_factory=ArtifactEntry)


class AuditTimestamp(BaseModel):
    """Simple started/completed audit entry."""

    started_at: str = ""
    completed_at: str = ""


class AuditReviewEntry(BaseModel):
    """Audit entry for a review phase with verdict tracking."""

    started_at: str = ""
    completed_at: str = ""
    baseline_commit: str = ""
    verdict: str = ""
    rounds: int = 0
    findings: list[ReviewFinding] = Field(default_factory=list)


class AuditState(BaseModel):
    """Audit trail for prepare lifecycle phases."""

    input_assessment: AuditTimestamp = Field(default_factory=AuditTimestamp)
    triangulation: AuditTimestamp = Field(default_factory=AuditTimestamp)
    requirements_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    test_spec_build: AuditTimestamp = Field(default_factory=AuditTimestamp)
    test_spec_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    plan_drafting: AuditTimestamp = Field(default_factory=AuditTimestamp)
    plan_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    gate: AuditTimestamp = Field(default_factory=AuditTimestamp)


class TodoState(BaseModel):
    """Canonical state for a TeleClaude work item (v1 schema).

    ``lifecycle_phase`` is the canonical software-development lifecycle step.
    ``phase`` remains the coarse pending/in_progress/done item status used by
    roadmap selection. ``prepare_phase`` and ``work_phase`` are retained only
    for legacy row compatibility and should remain empty in the current model.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    phase: str = "pending"
    lifecycle_phase: str = "input_assessment"
    prepare_phase: str = ""
    work_phase: str = ""
    build_start_base_sha: str = ""
    build_completed_at: str = ""
    kind: str = "todo"  # "todo" | "bug" | "draft" | "prepped"
    deferrals_processed: bool = False
    finalize: FinalizeModel = Field(default_factory=FinalizeModel)
    breakdown: BreakdownState = Field(default_factory=BreakdownState)
    grounding: GroundingState = Field(default_factory=GroundingState)
    dor: DorState | None = None
    requirements_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    test_spec_review: TestSpecReviewState = Field(default_factory=TestSpecReviewState)
    plan_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    build_review: BuildReviewState = Field(default_factory=BuildReviewState)
    artifacts: ArtifactsState = Field(default_factory=ArtifactsState)
    creative: dict[str, StateValue] | None = None
    audit: AuditState = Field(default_factory=AuditState)
    events: list[Event] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_display_fields(cls, data: object) -> object:
        """Drop legacy display-only fields before strict schema validation.

        Older todos.db rows may still carry ``current`` and
        ``integration_phase`` from the pre-authoritative-subphase model. They
        are derived/display concerns now, not part of the canonical mutation
        schema, so validation strips them and a subsequent write removes them
        from persistence.
        """
        if not isinstance(data, dict):
            return data

        legacy_keys = {"current", "integration_phase"}
        if not legacy_keys.intersection(data):
            return data

        cleaned = dict(data)
        for key in legacy_keys:
            cleaned.pop(key, None)
        return cleaned

    @classmethod
    def defaults(cls) -> TodoState:
        """Return a fresh v1 TodoState used by schema reset and scaffolding."""
        return cls()
