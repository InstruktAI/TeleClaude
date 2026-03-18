"""Pydantic models for Todo state management."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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
    worker_session_id: str = ""
    handed_off_at: str = ""
    handoff_session_id: str = ""


class GroundingState(BaseModel):
    """Grounding / freshness state."""

    valid: bool = False
    base_sha: str = ""
    input_digest: str = ""
    referenced_paths: list[str] = Field(default_factory=list)
    last_grounded_at: str = ""
    invalidated_at: str = ""
    invalidation_reason: str = ""


class ReviewVerdictState(BaseModel):
    """Verdict state for a prepare review phase."""

    verdict: str = ""
    reviewed_at: str = ""
    findings_count: int = 0
    rounds: int = 0
    baseline_commit: str = ""
    findings: list[str] = Field(default_factory=list)


class TestSpecReviewState(BaseModel):
    """Verdict state for test spec review (no baseline_commit/findings)."""

    verdict: str = ""
    reviewed_at: str = ""
    findings_count: int = 0
    rounds: int = 0


class ArtifactEntry(BaseModel):
    """Lifecycle stamp for a single artifact."""

    digest: str = ""
    produced_at: str = ""
    stale: bool = False


class ArtifactsState(BaseModel):
    """Artifact lifecycle stamps."""

    input: ArtifactEntry = Field(default_factory=ArtifactEntry)
    requirements: ArtifactEntry = Field(default_factory=ArtifactEntry)
    test_specs: ArtifactEntry = Field(default_factory=ArtifactEntry)
    implementation_plan: ArtifactEntry = Field(default_factory=ArtifactEntry)


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
    findings: list[str] = Field(default_factory=list)


class AuditState(BaseModel):
    """Audit trail for prepare lifecycle phases."""

    input_assessment: AuditTimestamp = Field(default_factory=AuditTimestamp)
    triangulation: AuditTimestamp = Field(default_factory=AuditTimestamp)
    requirements_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    plan_drafting: AuditTimestamp = Field(default_factory=AuditTimestamp)
    plan_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    gate: AuditTimestamp = Field(default_factory=AuditTimestamp)


class TodoState(BaseModel):
    """Canonical state for a TeleClaude work item."""

    schema_version: int = 1
    phase: str = "pending"
    kind: str = "todo"  # "todo" | "bug"
    build: str = "pending"
    review: str = "pending"
    deferrals_processed: bool = False
    finalize: FinalizeModel = Field(default_factory=FinalizeModel)
    breakdown: BreakdownState = Field(default_factory=BreakdownState)
    review_round: int = 0
    max_review_rounds: int = 3
    review_baseline_commit: str = ""
    unresolved_findings: list[str] = Field(default_factory=list)
    resolved_findings: list[str] = Field(default_factory=list)
    prepare_phase: str = ""
    grounding: GroundingState = Field(default_factory=GroundingState)
    requirements_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    test_spec_review: TestSpecReviewState = Field(default_factory=TestSpecReviewState)
    plan_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    artifacts: ArtifactsState = Field(default_factory=ArtifactsState)
    audit: AuditState = Field(default_factory=AuditState)
    dor: DorState | None = None
    requirements: ReviewVerdictState | None = None
    plan: ReviewVerdictState | None = None
