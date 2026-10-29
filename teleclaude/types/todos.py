"""Pydantic models for Todo state management (schema v13)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teleclaude.constants import TodoStatus
from teleclaude.types.lifecycle import LEGACY_LIFECYCLE_PHASE_NORMALIZATION, LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TodoKind

ACTIVE_RUNNER_STATE_KEY = "active_runner"
LIFECYCLE_PHASE_STATE_KEY = "lifecycle_phase"
PREPARED_SESSION_ID_STATE_KEY = "prepared_session_id"
SCHEMA_VERSION_STATE_KEY = "schema_version"


class DorActions(BaseModel):
    """Legacy-bridge: actions field from old DOR-format state files. Read-only for upcycle."""

    model_config = ConfigDict(extra="allow")
    requirements_updated: bool = False
    implementation_plan_updated: bool = False


class DorState(BaseModel):
    """Legacy-bridge: DOR field from old-format state files.

    The original Definition-of-Ready scoring system was never implemented — no
    code scores. This struct is retained solely so the legacy import and upcycle
    paths can read `status` as a phase-derivation hint when transforming pre-DB
    project state into the current model.
    """

    last_assessed_at: str | None = None
    score: int = 0
    status: str = "needs_work"  # legacy values: pass, needs_work, needs_decision
    schema_version: int = 1
    blockers: list[str] = Field(default_factory=list)
    actions_taken: DorActions | list[str] = Field(default_factory=DorActions)


class BreakdownState(BaseModel):
    """Breakdown assessment state for complex todos."""

    assessed: bool = False
    todos: list[str] = Field(default_factory=list)


class FinalizeStatus(StrEnum):
    """Closed lifecycle status of a todo's finalize claim."""

    PENDING = "pending"
    READY = "ready"


class FinalizeField(StrEnum):
    """Field names in the raw persisted finalize-state mapping."""

    STATUS = "status"


class FinalizeModel(BaseModel):
    """Finalize phase state."""

    status: FinalizeStatus = FinalizeStatus.PENDING
    branch: str = ""
    sha: str = ""
    ready_at: str = ""
    worker_session_id: str = ""


class ApprovalStamp(BaseModel):
    """Human approval stamp for a prepare artifact."""

    approved: bool = False
    approved_at: str = ""
    caller_session_id: str = ""
    approved_digest: str = ""


class SkipStamp(BaseModel):
    """Skip stamp for an optional prepare phase."""

    reason: str = ""
    skipped_at: str = ""
    caller_session_id: str = ""


class DependencyEntry(BaseModel):
    """Snapshot of a direct todo dependency and its todo status."""

    dep_slug: str
    todo_status: TodoStatus


class DriftReviewedStamp(BaseModel):
    """Drift review verdict for one prepare artifact."""

    verdict: Literal["substantive", "cosmetic"]
    reason: str = ""
    stamped_at: str = ""
    caller_session_id: str = ""
    head_sha_at_review: str = ""
    upstream_digests_at_review: dict[str, str] = Field(default_factory=dict)
    snippet_digests_at_review: dict[str, str] = Field(default_factory=dict)
    dependency_digests_at_review: dict[str, dict[str, str]] = Field(default_factory=dict)


class ApprovalsState(BaseModel):
    """Prepare v2 gate, skip, and drift review stamps."""

    prd_approved: ApprovalStamp = Field(default_factory=ApprovalStamp)
    architecture_approved: ApprovalStamp = Field(default_factory=ApprovalStamp)
    plan_approved: ApprovalStamp = Field(default_factory=ApprovalStamp)
    task_approved: ApprovalStamp = Field(default_factory=ApprovalStamp)
    # The bug lane's settlement stamp: the driving prepare session records the
    # `diagnosis` artifact's digest once the interrogation's two settlement
    # conditions hold. Digest-bound like every other approval, but the caller
    # is never required to resolve to a human — the driver is an agent.
    diagnosis_settled: ApprovalStamp = Field(default_factory=ApprovalStamp)
    architecture_skipped: SkipStamp | None = None
    drift_reviewed: dict[str, DriftReviewedStamp] = Field(default_factory=dict)


class ReviewCycleState(BaseModel):
    """Cycle offsets scoped to one prepare-review target."""

    round_offset: int = Field(ge=0, default=0)
    reconciliation_pending: bool = False


class ReviewVerdictState(BaseModel):
    """Verdict state for a prepare review phase.

    ``rounds`` counts admitted reviewer-dispatch passes and advances immediately
    before the reviewer instruction is emitted.
    """

    verdict: str = ""
    reviewed_at: str = ""
    rounds: int = 0
    baseline_commit: str = ""
    reviewed_target_digest: str = ""
    review_report_digest: str = ""
    caller_session_id: str = ""
    cleared_by_substantive_drift: bool = False
    cycle: ReviewCycleState = Field(default_factory=ReviewCycleState)

    def open_new_cycle(self) -> None:
        """Start a review cycle at the current cumulative history boundary."""
        self.cycle.round_offset = self.rounds
        self.cycle.reconciliation_pending = False

    @model_validator(mode="after")
    def _validate_cycle_offsets(self) -> ReviewVerdictState:
        """Keep cycle offsets inside the cumulative history they project."""
        if self.cycle.round_offset > self.rounds:
            raise ValueError("review cycle round_offset cannot exceed cumulative rounds")
        return self


class BuildReviewState(BaseModel):
    """Verdict state for the work (build) review phase.

    Unlike prepare reviews, the build review tracks a baseline_commit so that
    re-review dispatch can restrict diff scope to commits since the last verdict.
    ``round`` counts admitted reviewer-dispatch passes and advances immediately
    before a fresh or reused reviewer instruction is emitted.
    """

    verdict: str = ""
    reviewed_at: str = ""
    round: int = 0
    baseline_commit: str = ""
    dispatch_head: str = ""
    reviewed_target_digest: str = ""
    review_report_digest: str = ""
    caller_session_id: str = ""


class HoldAuditSource(StrEnum):
    """Closed vocabulary for what set the current hold brake."""

    NONE = ""
    CREATION = "creation"
    MANUAL = "manual"
    SESSION_CLOSE = "session_close"
    TASK_ERROR = "task_error"
    DIAGNOSIS_UNRESOLVED = "diagnosis_unresolved"
    KIND_BACKFILL = "kind_backfill"


class HoldAuditReason(StrEnum):
    """Closed compatibility tokens used by the hold-audit projection."""

    LEGACY_UPDATE_COMMAND = "todo update"
    LEGACY_CREATE_COMMAND = "todo create --hold"
    UNKNOWN = "reason-unknown"


class HoldAuditState(BaseModel):
    """Diagnostic metadata for the current hold brake."""

    model_config = ConfigDict(use_enum_values=True)

    source: HoldAuditSource = HoldAuditSource.NONE
    set_at: str = ""
    set_by_session_id: str = ""
    reason: str = ""


class TodoEventKind(StrEnum):
    """Closed vocabulary of ``Event.kind`` values the lifecycle reads back."""

    BUILD_REVIEW_STAMP = "build_review_stamp"
    COMMIT_REVIEW_STAMP = "commit_review_stamp"
    CODE_CONFORMANCE_RETURN = "code_conformance_return"
    PREPARE_CLAIM = "prepare_claim"
    TASK_FIRING_STARTED = "task_firing_started"


class TaskStamp(StrEnum):
    """Task-lane stamp types dispatched through this discriminator (the firing-start stamp)."""

    FIRING_STARTED = "task_firing_started"


class CommitReviewVerdict(StrEnum):
    """Outcome a commit-review stamp records on a commit SHA."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class CommitReviewDetail(StrEnum):
    """Keys of a commit-review stamp event's ``details`` payload."""

    SHA = "sha"
    VERDICT = "verdict"
    REASON = "reason"


class BuildReviewDetail(StrEnum):
    """Keys of a build-review stamp event's ``details`` payload."""

    ROUND = "round"
    COMMIT = "commit"
    VERDICT = "verdict"
    REPORT_DIGEST = "report_digest"


class PrepareClaimDetail(StrEnum):
    """Keys of a prepare-claim event's ``details`` payload."""

    MAIN_HEAD = "main_head"


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
    dependency_artifact_digests: dict[str, dict[str, str]] = Field(default_factory=dict)
    codebase_sha_at_write: str = ""
    referenced_paths: list[str] = Field(default_factory=list)
    owned_snippet_digests: dict[str, str] = Field(default_factory=dict)
    referenced_snippet_digests: dict[str, str] = Field(default_factory=dict)
    async_provenance_complete: bool = False
    # True when this artifact was supplied at creation (e.g. `--plan`) and has not
    # yet been processed by its drafting pass; cleared on first rewrite.
    seeded: bool = False


class ArtifactsState(BaseModel):
    """Artifact lifecycle stamps."""

    input: ArtifactEntry = Field(default_factory=ArtifactEntry)
    prd: ArtifactEntry = Field(default_factory=ArtifactEntry)
    requirements: ArtifactEntry = Field(default_factory=ArtifactEntry)
    architecture: ArtifactEntry = Field(default_factory=ArtifactEntry)
    diagnosis: ArtifactEntry = Field(default_factory=ArtifactEntry)
    implementation_plan: ArtifactEntry = Field(default_factory=ArtifactEntry)
    task_plan: ArtifactEntry = Field(default_factory=ArtifactEntry)
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

    prd_drafting: AuditTimestamp = Field(default_factory=AuditTimestamp)
    prd_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    requirements_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    architecture_drafting: AuditTimestamp = Field(default_factory=AuditTimestamp)
    architecture_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)
    plan_drafting: AuditTimestamp = Field(default_factory=AuditTimestamp)
    plan_review: AuditReviewEntry = Field(default_factory=AuditReviewEntry)


class TodoState(BaseModel):
    """Canonical state for a TeleClaude work item (schema v13).

    ``lifecycle_phase`` is the only authoritative sdlc phase
    pointer. ``phase`` remains the coarse pending/in_progress/done item status
    used by todo selection.

    ``prepare_phase`` and ``work_phase`` remain as transient compatibility
    fields so older code paths can still validate during the migration window,
    but they are excluded from persistence and must not be used as authority.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[13] = 13
    phase: str = "pending"
    lifecycle_phase: LifecyclePhase = LifecyclePhase.DRAFT
    prepare_phase: str = Field(default="", exclude=True)
    work_phase: str = Field(default="", exclude=True)
    build_start_base_sha: str = ""
    build_plan_digest: str = ""
    build_completed_at: str = ""
    build_gate_claim_at: str = ""
    kind: TodoKind = TodoKind.FEATURE
    hold: bool = False
    hold_audit: HoldAuditState = Field(default_factory=HoldAuditState)
    active_runner: str | None = None
    prepared_session_id: str | None = None
    manually_started: bool = False
    deferrals_processed: bool = False
    finalize: FinalizeModel = Field(default_factory=FinalizeModel)
    breakdown: BreakdownState = Field(default_factory=BreakdownState)
    approvals: ApprovalsState = Field(default_factory=ApprovalsState)
    dor: DorState | None = None  # legacy-bridge; populated only by import/upcycle of old state
    prd_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    requirements_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
    architecture_review: ReviewVerdictState = Field(default_factory=ReviewVerdictState)
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
        """Normalize legacy fields before strict schema validation.

        Older todos.db rows may still carry ``current`` from the pre-canonical
        lifecycle model. Validation strips it so a subsequent write removes it
        from persistence. Rows persisted on removed downstream approval phases
        are normalized back to the corresponding review phase so prepare can
        re-adopt the next pointer from reviewer verdicts.
        """
        if not isinstance(data, dict):
            return data

        # ``current`` is pre-canonical display state. ``test_spec_review`` is a
        # removed top-level verdict field (test-specs phase deleted under the
        # doc-first model); strip it so ``extra="forbid"`` does not reject rows
        # persisted before the cutover.
        legacy_keys = {"current", "test_spec_review"}
        lifecycle_phase = data.get("lifecycle_phase")
        if not legacy_keys.intersection(data) and lifecycle_phase not in LEGACY_LIFECYCLE_PHASE_NORMALIZATION:
            return data

        cleaned = dict(data)
        for key in legacy_keys:
            cleaned.pop(key, None)
        if isinstance(lifecycle_phase, str):
            cleaned["lifecycle_phase"] = LEGACY_LIFECYCLE_PHASE_NORMALIZATION.get(lifecycle_phase, lifecycle_phase)
        return cleaned

    @classmethod
    def defaults(cls) -> TodoState:
        """Return a fresh v11 TodoState used by schema reset and scaffolding."""
        return cls()
