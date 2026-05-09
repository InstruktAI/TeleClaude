"""Pydantic models for Todo state management (schema v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teleclaude.types.state_value import StateValue

LifecyclePhaseValue = Literal[
    "draft",
    "input_assessment",
    "triangulation",
    "requirements_review",
    "requirements_human_approval",
    "test_spec_build",
    "test_spec_review",
    "plan_drafting",
    "plan_review",
    "gate",
    "grounding_check",
    "re_grounding",
    "prepared",
    "build_started",
    "build_complete",
    "review_changes_requested",
    "review_approved",
    "finalize_ready",
    "handed_off",
]


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


class PreparePairSlot(BaseModel):
    """Durable identity for one prepare pair member.

    Stores both the TC ``session_id`` (used for tail/send while the row exists)
    and ``native_session_id`` + ``agent`` (used for ``telec sessions revive``
    after the TC row is purged — closed sessions are removed after the 7-day
    retention window in ``maintenance_service._cleanup_inactive_sessions``).
    """

    session_id: str
    native_session_id: str = ""
    agent: str
    lens: Literal["A", "B"]


class PreparePair(BaseModel):
    """Durable prepare pair identity stored across pair-owned phases."""

    slot_a: PreparePairSlot | None = None
    slot_b: PreparePairSlot | None = None


class ReviewVerdictState(BaseModel):
    """Verdict state for a prepare review phase."""

    verdict: str = ""
    reviewed_at: str = ""
    rounds: int = 0
    baseline_commit: str = ""
    approved_digest: str = ""


class TestSpecReviewState(BaseModel):
    """Verdict state for test spec review (no baseline_commit)."""

    verdict: str = ""
    reviewed_at: str = ""
    rounds: int = 0
    approved_digest: str = ""


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

    model_config = ConfigDict(extra="ignore")

    digest: str = ""
    produced_at: str = ""
    approved: bool = False
    confirmed: bool = False
    upstream_digests: dict[str, str] = Field(default_factory=dict)


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
    """Canonical state for a TeleClaude work item (schema v2).

    ``lifecycle_phase`` is the only authoritative software-development phase
    pointer. ``phase`` remains the coarse pending/in_progress/done item status
    used by roadmap selection.

    ``prepare_phase`` and ``work_phase`` remain as transient compatibility
    fields so older code paths can still validate during the migration window,
    but they are excluded from persistence and must not be used as authority.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    phase: str = "pending"
    lifecycle_phase: LifecyclePhaseValue = "input_assessment"
    prepare_phase: str = Field(default="", exclude=True)
    work_phase: str = Field(default="", exclude=True)
    build_start_base_sha: str = ""
    build_completed_at: str = ""
    build_gate_claim_at: str = ""
    kind: str = "todo"  # "todo" | "bug" | "draft" | "prepped"
    deferrals_processed: bool = False
    finalize: FinalizeModel = Field(default_factory=FinalizeModel)
    breakdown: BreakdownState = Field(default_factory=BreakdownState)
    grounding: GroundingState = Field(default_factory=GroundingState)
    dor: DorState | None = None
    prepare_pair: PreparePair | None = None
    requirements_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    test_spec_review: TestSpecReviewState = Field(default_factory=TestSpecReviewState)
    plan_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    build_review: BuildReviewState = Field(default_factory=BuildReviewState)
    artifacts: ArtifactsState = Field(default_factory=ArtifactsState)
    creative: dict[str, StateValue] | None = None
    integration_phase: str | None = None
    audit: AuditState = Field(default_factory=AuditState)
    events: list[Event] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_display_fields(cls, data: object) -> object:
        """Drop legacy display-only fields before strict schema validation.

        Older todos.db rows may still carry ``current`` from the pre-canonical
        lifecycle model. Validation strips it so a subsequent write removes it
        from persistence.
        """
        if not isinstance(data, dict):
            return data

        legacy_keys = {"current"}
        if not legacy_keys.intersection(data):
            return data

        cleaned = dict(data)
        for key in legacy_keys:
            cleaned.pop(key, None)
        return cleaned

    @classmethod
    def defaults(cls) -> TodoState:
        """Return a fresh v2 TodoState used by schema reset and scaffolding."""
        return cls()
