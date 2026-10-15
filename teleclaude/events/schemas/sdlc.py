"""Workflow-owned event declarations: the sdlc domain's todo, planning, review, integration and deployment events.

The workflow context authors each declaration's values and states each event's
subject and home; the event catalog owns the declaration shape.
"""

from __future__ import annotations

from pydantic import JsonValue

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import ComputerRef, DeploymentRef, SessionRef, TodoRef
from teleclaude.types.workflow_record import WaitedPhase

_PROJECT_HOME = (EventHomeKind.PROJECT,)


class TodoSlugData(EventData):
    """The slug of the todo an event reports on."""

    slug: str


class TodoCreatedData(EventData):
    context: str | None = None
    created_at: str
    creation_mode: str
    entry_point: str | None = None
    human_involved: bool
    kind: str
    lifecycle_phase: str | None = None
    lineage: str | None = None
    pickup_requested: bool
    project_path: str
    slug: str


class TodoDeliveredData(EventData):
    delivered_at: str
    delivery_commit: str | None = None
    project_path: str
    slug: str


class TodoPhaseAdvancedData(EventData):
    lifecycle_phase: str
    prior_lifecycle_phase: str
    project_path: str
    slug: str


class TodoUpdatedData(EventData):
    project_path: str
    slug: str
    updated_at: str


class TodoFinalizeReadyData(EventData):
    branch: str
    project_path: str
    ready_at: str
    sha: str
    slug: str
    worker_session_id: str


class TodoClaimChangedData(EventData):
    holder: str | None = None
    prior_holder: str | None = None
    project_path: str
    slug: str


class TodoHeadAdvancedData(EventData):
    branch: str
    project_path: str
    sha: str
    slug: str


class TodoWaitingData(EventData):
    person: str
    project_path: str
    slug: str
    waited_phase: WaitedPhase


class TodoReadyData(EventData):
    branch: str
    driver_session_id: str
    project_path: str
    ready_at: str
    sha: str
    slug: str


class TodoDriverRequestData(EventData):
    project_path: str
    requested_by: str
    reservation_key: str
    slug: str


class DorAssessedData(EventData):
    score: JsonValue | None = None
    slug: str
    verdict: JsonValue | None = None


class ArtifactInvalidatedData(EventData):
    slug: str
    stale_artifacts: JsonValue | None = None


class ArtifactProducedData(EventData):
    artifact: str
    digest: str
    slug: str


class PrepareBlockedData(EventData):
    blocker: JsonValue | None = None
    slug: str


class PrepareDiscoveryStartedData(EventData):
    slug: str | None = None


class PhaseSkippedData(EventData):
    phase: JsonValue | None = None
    reason: JsonValue | None = None
    slug: str


class ReviewScopedData(EventData):
    findings_artifact: JsonValue | None = None
    slug: str


class ReviewApprovedData(EventData):
    approved_at: str
    review_round: int
    reviewer_session_id: str
    slug: str


class ReviewNeedsDecisionData(EventData):
    question: JsonValue | None = None
    round: JsonValue | None = None
    slug: str


class ReviewVerdictReadyData(EventData):
    round: JsonValue | None = None
    slug: str
    verdict: JsonValue | None = None


class BranchPushedData(EventData):
    branch: str
    pushed_at: JsonValue | None = None


class DeployTriggeredData(EventData):
    environment: JsonValue | None = None
    slug: str | None = None


class DeployFailedData(EventData):
    error: JsonValue | None = None
    slug: str


class DeploymentStartedData(EventData):
    ready_at: JsonValue | None = None
    slug: str


class DeploymentCompletedData(EventData):
    branch: str
    integrated_at: str
    merge_commit: str
    sha: str
    slug: str


class DeploymentFailedData(EventData):
    blocked_at: str
    branch: str
    conflict_evidence: list[str]
    diagnostics: list[str]
    sha: str
    slug: str


class IntegrationStartedData(EventData):
    queue_depth: int
    session_id: str
    slug: str


class CandidateDeliveredData(EventData):
    branch: str
    integrated_at: str
    merge_commit_sha: str
    slug: str


class CandidateBlockedData(EventData):
    blocked_at: str
    branch: str
    reason: str
    sha: str
    slug: str


class CandidateParkedData(EventData):
    branch: str
    parked_at: str
    reason: str
    sha: str
    slug: str


class ParkedCandidateData(CandidateParkedData):
    """One candidate a drain set aside."""


class DrainCompletedData(EventData):
    completed_at: str
    delivered_count: int
    parked: list[ParkedCandidateData]
    session_id: str


class SchedulerTickData(EventData):
    computer: str
    ticked_at: str


class TodoCreated(PlatformEvent[TodoRef, TodoCreatedData]):
    NAME = "sdlc.todo.created"
    DESCRIPTION = "A workflow todo was created and may require lifecycle-runner evaluation"
    HOME_KINDS = _PROJECT_HOME


class TodoUpdated(PlatformEvent[TodoRef, TodoUpdatedData]):
    NAME = "sdlc.todo.updated"
    DESCRIPTION = "A workflow todo control-plane field changed and may affect runner eligibility"
    HOME_KINDS = _PROJECT_HOME


class TodoPhaseAdvanced(PlatformEvent[TodoRef, TodoPhaseAdvancedData]):
    NAME = "sdlc.todo.phase_advanced"
    DESCRIPTION = "A workflow todo advanced lifecycle phase and may unblock runner work"
    HOME_KINDS = _PROJECT_HOME


class TodoDelivered(PlatformEvent[TodoRef, TodoDeliveredData]):
    NAME = "sdlc.todo.delivered"
    DESCRIPTION = "A workflow todo was delivered and may unblock dependents"
    HOME_KINDS = _PROJECT_HOME


class RoadmapEntryMoved(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.roadmap.entry_moved"
    DESCRIPTION = "A roadmap entry moved between queues or dependency positions"
    HOME_KINDS = _PROJECT_HOME


class TodoClaimChanged(PlatformEvent[TodoRef, TodoClaimChangedData]):
    NAME = "sdlc.todo.claim_changed"
    DESCRIPTION = "The session holding a workflow todo's claim changed"
    HOME_KINDS = _PROJECT_HOME


class TodoHeadAdvanced(PlatformEvent[TodoRef, TodoHeadAdvancedData]):
    NAME = "sdlc.todo.head_advanced"
    DESCRIPTION = "A commit was observed on a workflow todo's integration ref"
    HOME_KINDS = _PROJECT_HOME


class TodoWaiting(PlatformEvent[TodoRef, TodoWaitingData]):
    NAME = "sdlc.todo.waiting"
    DESCRIPTION = "A workflow todo waits on a question only a named person can answer"
    HOME_KINDS = _PROJECT_HOME


class TodoReady(PlatformEvent[TodoRef, TodoReadyData]):
    NAME = "sdlc.todo.ready"
    DESCRIPTION = "A workflow todo is ready at a stamped commit and is a candidate for integration"
    HOME_KINDS = _PROJECT_HOME


class TodoPreparationRequested(PlatformEvent[TodoRef, TodoDriverRequestData]):
    NAME = "sdlc.todo.preparation_requested"
    DESCRIPTION = "A workflow todo's preparation needs its driver session started"
    HOME_KINDS = _PROJECT_HOME


class TodoWorkRequested(PlatformEvent[TodoRef, TodoDriverRequestData]):
    NAME = "sdlc.todo.work_requested"
    DESCRIPTION = "A workflow todo's work needs its driver session started"
    HOME_KINDS = _PROJECT_HOME


class TodoFinalizeReady(PlatformEvent[TodoRef, TodoFinalizeReadyData]):
    NAME = "sdlc.planning.todo_finalize_ready"
    DESCRIPTION = "Finalize-ready worker claim is ready for integration handoff"
    HOME_KINDS = _PROJECT_HOME


class DorAssessed(PlatformEvent[TodoRef, DorAssessedData]):
    NAME = "sdlc.planning.dor_assessed"
    DESCRIPTION = "Definition of Ready was assessed for a work item"
    HOME_KINDS = _PROJECT_HOME


class PrepareArtifactInvalidated(PlatformEvent[TodoRef, ArtifactInvalidatedData]):
    NAME = "sdlc.prepare.artifact_invalidated"
    DESCRIPTION = "Upstream change cascaded staleness to a prepare artifact"
    HOME_KINDS = _PROJECT_HOME


class PrepareArtifactProduced(PlatformEvent[TodoRef, ArtifactProducedData]):
    NAME = "sdlc.prepare.artifact_produced"
    DESCRIPTION = "Prepare artifact written and lifecycle-tracked in state"
    HOME_KINDS = _PROJECT_HOME


class PrepareBlocked(PlatformEvent[TodoRef, PrepareBlockedData]):
    NAME = "sdlc.prepare.blocked"
    DESCRIPTION = "Preparation blocked, requires human decision"
    HOME_KINDS = _PROJECT_HOME


class PrepareCompleted(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.completed"
    DESCRIPTION = "Preparation complete, todo ready for build"
    HOME_KINDS = _PROJECT_HOME


class PrepareDiscoveryStarted(PlatformEvent[TodoRef, PrepareDiscoveryStartedData]):
    NAME = "sdlc.prepare.discovery_started"
    DESCRIPTION = "Requirements discovery phase dispatched"
    HOME_KINDS = _PROJECT_HOME


class PrepareInputConsumed(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.input_consumed"
    DESCRIPTION = "Input consumed by discovery worker, requirements production started"
    HOME_KINDS = _PROJECT_HOME


class PrepareInputRefined(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.input_refined"
    DESCRIPTION = "Human thinking was captured or updated in input.md"
    HOME_KINDS = _PROJECT_HOME


class PreparePhaseSkipped(PlatformEvent[TodoRef, PhaseSkippedData]):
    NAME = "sdlc.prepare.phase_skipped"
    DESCRIPTION = "Prepare phase skipped via inheritance from parent todo"
    HOME_KINDS = _PROJECT_HOME


class PreparePlanApproved(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.plan_approved"
    DESCRIPTION = "Implementation plan reviewed and approved"
    HOME_KINDS = _PROJECT_HOME


class PreparePlanDrafted(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.plan_drafted"
    DESCRIPTION = "Implementation plan drafted from approved requirements"
    HOME_KINDS = _PROJECT_HOME


class PrepareRequirementsApproved(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.requirements_approved"
    DESCRIPTION = "Requirements reviewed and approved, ready for plan drafting"
    HOME_KINDS = _PROJECT_HOME


class PrepareRequirementsDrafted(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.prepare.requirements_drafted"
    DESCRIPTION = "Requirements derived from triangulation"
    HOME_KINDS = _PROJECT_HOME


class PrepareReviewScoped(PlatformEvent[TodoRef, ReviewScopedData]):
    NAME = "sdlc.prepare.review_scoped"
    DESCRIPTION = "Scoped re-review dispatched with a findings artifact"
    HOME_KINDS = _PROJECT_HOME


class BuildCompleted(PlatformEvent[TodoRef, TodoSlugData]):
    NAME = "sdlc.build.completed"
    DESCRIPTION = "Build phase completed for a work item"
    HOME_KINDS = _PROJECT_HOME


class ReviewApproved(PlatformEvent[TodoRef, ReviewApprovedData]):
    NAME = "sdlc.review.approved"
    DESCRIPTION = "Review passed, candidate eligible for finalization"
    HOME_KINDS = _PROJECT_HOME


class ReviewNeedsDecision(PlatformEvent[TodoRef, ReviewNeedsDecisionData]):
    NAME = "sdlc.review.needs_decision"
    DESCRIPTION = "Review requires a human decision before proceeding"
    HOME_KINDS = _PROJECT_HOME


class ReviewVerdictReady(PlatformEvent[TodoRef, ReviewVerdictReadyData]):
    NAME = "sdlc.review.verdict_ready"
    DESCRIPTION = "Code review verdict is ready"
    HOME_KINDS = _PROJECT_HOME


class BranchPushed(PlatformEvent[TodoRef, BranchPushedData]):
    NAME = "sdlc.branch.pushed"
    DESCRIPTION = "Worktree branch pushed to remote, candidate ready for integration"
    HOME_KINDS = _PROJECT_HOME


class DeployTriggered(PlatformEvent[DeploymentRef, DeployTriggeredData]):
    NAME = "sdlc.deploy.triggered"
    DESCRIPTION = "Deployment was triggered for a work item"
    HOME_KINDS = _PROJECT_HOME


class DeploySucceeded(PlatformEvent[DeploymentRef, TodoSlugData]):
    NAME = "sdlc.deploy.succeeded"
    DESCRIPTION = "Deployment completed successfully"
    HOME_KINDS = _PROJECT_HOME


class DeployFailed(PlatformEvent[DeploymentRef, DeployFailedData]):
    NAME = "sdlc.deploy.failed"
    DESCRIPTION = "Deployment failed and requires attention"
    HOME_KINDS = _PROJECT_HOME


class DeploymentStarted(PlatformEvent[DeploymentRef, DeploymentStartedData]):
    NAME = "sdlc.deployment.started"
    DESCRIPTION = "Finalize ready, candidate queued for integration"
    HOME_KINDS = _PROJECT_HOME


class DeploymentCompleted(PlatformEvent[DeploymentRef, DeploymentCompletedData]):
    NAME = "sdlc.deployment.completed"
    DESCRIPTION = "Integrated to main, delivery bookkeeping done"
    HOME_KINDS = _PROJECT_HOME


class DeploymentFailed(PlatformEvent[DeploymentRef, DeploymentFailedData]):
    NAME = "sdlc.deployment.failed"
    DESCRIPTION = "Integration blocked, needs attention"
    HOME_KINDS = _PROJECT_HOME


class IntegrationStarted(PlatformEvent[TodoRef, IntegrationStartedData]):
    NAME = "sdlc.integration.started"
    DESCRIPTION = "An integrator began processing a candidate"
    HOME_KINDS = _PROJECT_HOME


class IntegrationCandidateDelivered(PlatformEvent[TodoRef, CandidateDeliveredData]):
    NAME = "sdlc.integration.candidate.delivered"
    DESCRIPTION = "An integration candidate completed delivery"
    HOME_KINDS = _PROJECT_HOME


class IntegrationCandidateBlocked(PlatformEvent[TodoRef, CandidateBlockedData]):
    NAME = "sdlc.integration.candidate.blocked"
    DESCRIPTION = "An integration candidate was blocked"
    HOME_KINDS = _PROJECT_HOME


class IntegrationCandidateParked(PlatformEvent[TodoRef, CandidateParkedData]):
    NAME = "sdlc.integration.candidate.parked"
    DESCRIPTION = "An integration candidate was parked for the current drain"
    HOME_KINDS = _PROJECT_HOME


class IntegrationDrainCompleted(PlatformEvent[SessionRef, DrainCompletedData]):
    NAME = "sdlc.integration.drain.completed"
    DESCRIPTION = "An integration drain completed with delivered and parked outcomes"
    HOME_KINDS = _PROJECT_HOME


class SchedulerTickMinute(PlatformEvent[ComputerRef, SchedulerTickData]):
    NAME = "teleclaude.scheduler.tick.minute"
    DESCRIPTION = "Daemon minute wake-up for schedule-gated workflow evaluation"


DECLARED: tuple[DeclaredEvent, ...] = (
    TodoCreated,
    TodoUpdated,
    TodoPhaseAdvanced,
    TodoDelivered,
    RoadmapEntryMoved,
    TodoFinalizeReady,
    TodoClaimChanged,
    TodoHeadAdvanced,
    TodoWaiting,
    TodoReady,
    TodoPreparationRequested,
    TodoWorkRequested,
    DorAssessed,
    PrepareArtifactInvalidated,
    PrepareArtifactProduced,
    PrepareBlocked,
    PrepareCompleted,
    PrepareDiscoveryStarted,
    PrepareInputConsumed,
    PrepareInputRefined,
    PreparePhaseSkipped,
    PreparePlanApproved,
    PreparePlanDrafted,
    PrepareRequirementsApproved,
    PrepareRequirementsDrafted,
    PrepareReviewScoped,
    BuildCompleted,
    ReviewApproved,
    ReviewNeedsDecision,
    ReviewVerdictReady,
    BranchPushed,
    DeployTriggered,
    DeploySucceeded,
    DeployFailed,
    DeploymentStarted,
    DeploymentCompleted,
    DeploymentFailed,
    IntegrationStarted,
    IntegrationCandidateDelivered,
    IntegrationCandidateBlocked,
    IntegrationCandidateParked,
    IntegrationDrainCompleted,
    SchedulerTickMinute,
)
