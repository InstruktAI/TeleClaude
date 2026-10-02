"""Software development domain event schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.events.catalog import (
    EventSchema,
    LifecycleFamily,
    NotificationLifecycle,
    PayloadField,
    PayloadValueKind,
    SubjectAssignment,
)
from teleclaude.events.envelope import EventHomeKind, EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


class IntegrationEventType(StrEnum):
    """Closed taxonomy for integration lifecycle events on the platform stream."""

    STARTED = "domain.sdlc.integration.started"
    CANDIDATE_DELIVERED = "domain.sdlc.integration.candidate.delivered"
    CANDIDATE_BLOCKED = "domain.sdlc.integration.candidate.blocked"
    CANDIDATE_PARKED = "domain.sdlc.integration.candidate.parked"
    DRAIN_COMPLETED = "domain.sdlc.integration.drain.completed"


_SUBJECT_ASSIGNMENT_SCHEDULE = SubjectAssignment(kinds=[], about="the platform schedule clock")
_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT], about="the project whose workflow activity this event records"
)
_SDLC_DOMAIN = "sdlc"
_INTEGRATION_STARTED_DESCRIPTION = "An integrator began processing a candidate"
_INTEGRATION_CANDIDATE_DELIVERED_DESCRIPTION = "An integration candidate completed delivery"
_INTEGRATION_CANDIDATE_BLOCKED_DESCRIPTION = "An integration candidate was blocked"
_PAYLOAD_FIELDS_DOMAIN_SDLC_BRANCH_PUSHED: list[PayloadField] = [
    PayloadField(name="branch", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="pushed_at", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_BUILD_COMPLETED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_FAILED: list[PayloadField] = [
    PayloadField(name="error", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_SUCCEEDED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_TRIGGERED: list[PayloadField] = [
    PayloadField(name="environment", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_COMPLETED: list[PayloadField] = [
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="integrated_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="merge_commit", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_FAILED: list[PayloadField] = [
    PayloadField(name="blocked_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="conflict_evidence", kind=PayloadValueKind.ARRAY, nullable=False),
    PayloadField(name="diagnostics", kind=PayloadValueKind.ARRAY, nullable=False),
    PayloadField(name="next_action", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_STARTED: list[PayloadField] = [
    PayloadField(name="ready_at", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_STARTED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="session_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="queue_depth", kind=PayloadValueKind.INTEGER, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_DELIVERED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="merge_commit_sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="integrated_at", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_BLOCKED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="reason", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="blocked_at", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_PARKED: list[PayloadField] = [
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="parked_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="reason", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_DRAIN_COMPLETED: list[PayloadField] = [
    PayloadField(name="completed_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="delivered_count", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="parked", kind=PayloadValueKind.ARRAY, nullable=False),
    PayloadField(name="session_id", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_MAINTENANCE_DEPENDENCY_UPDATE: list[PayloadField] = [
    PayloadField(name="package", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="version", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_MAINTENANCE_SECURITY_PATCH: list[PayloadField] = [
    PayloadField(name="advisory_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="severity", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_OPS_ALERT_FIRED: list[PayloadField] = [
    PayloadField(name="alert_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="severity", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_OPS_ALERT_RESOLVED: list[PayloadField] = [
    PayloadField(name="alert_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PLANNING_DOR_ASSESSED: list[PayloadField] = [
    PayloadField(name="score", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="verdict", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PLANNING_TODO_FINALIZE_READY: list[PayloadField] = [
    PayloadField(name="branch", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="ready_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="sha", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="worker_session_id", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_ARTIFACT_INVALIDATED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="stale_artifacts", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_ARTIFACT_PRODUCED: list[PayloadField] = [
    PayloadField(name="artifact", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="digest", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_BLOCKED: list[PayloadField] = [
    PayloadField(name="blocker", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_COMPLETED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_DISCOVERY_STARTED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_INPUT_CONSUMED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_INPUT_REFINED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PHASE_SKIPPED: list[PayloadField] = [
    PayloadField(name="phase", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="reason", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PLAN_APPROVED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PLAN_DRAFTED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REQUIREMENTS_APPROVED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REQUIREMENTS_DRAFTED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REVIEW_SCOPED: list[PayloadField] = [
    PayloadField(name="findings_artifact", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_APPROVED: list[PayloadField] = [
    PayloadField(name="approved_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="review_round", kind=PayloadValueKind.INTEGER, nullable=False),
    PayloadField(name="reviewer_session_id", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_NEEDS_DECISION: list[PayloadField] = [
    PayloadField(name="question", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="round", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_VERDICT_READY: list[PayloadField] = [
    PayloadField(name="round", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="verdict", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_SCHEDULER_TICK_MINUTE: list[PayloadField] = [
    PayloadField(name="computer", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="ticked_at", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_WORKFLOW_ROADMAP_ENTRY_MOVED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_WORKFLOW_TODO_CREATED: list[PayloadField] = [
    PayloadField(name="context", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="created_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="creation_mode", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="entry_point", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="human_involved", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="kind", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="lifecycle_phase", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="lineage", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="pickup_requested", kind=PayloadValueKind.BOOLEAN, nullable=False),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_WORKFLOW_TODO_DELIVERED: list[PayloadField] = [
    PayloadField(name="delivered_at", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="delivery_commit", kind=PayloadValueKind.STRING, nullable=True),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_WORKFLOW_TODO_PHASE_ADVANCED: list[PayloadField] = [
    PayloadField(name="lifecycle_phase", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="prior_lifecycle_phase", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
]
_PAYLOAD_FIELDS_WORKFLOW_TODO_UPDATED: list[PayloadField] = [
    PayloadField(name="project_path", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="slug", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="updated_at", kind=PayloadValueKind.STRING, nullable=False),
]


def register_sdlc(catalog: EventCatalog) -> None:
    """Register sdlc domain event schemas."""
    catalog.register(
        EventSchema(
            event_type="scheduler.tick.minute",
            description="Daemon minute wake-up for schedule-gated workflow evaluation",
            subject_assignment=_SUBJECT_ASSIGNMENT_SCHEDULE,
            payload_fields=_PAYLOAD_FIELDS_SCHEDULER_TICK_MINUTE,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(updates=True, meaningful_fields=["ticked_at", "computer"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.created",
            description="A workflow todo was created and may require lifecycle-runner evaluation",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_WORKFLOW_TODO_CREATED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key="slug",
                family=LifecycleFamily.TODO_LIFECYCLE,
                meaningful_fields=["slug", "kind"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.phase_advanced",
            description="A workflow todo advanced lifecycle phase and may unblock runner work",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_WORKFLOW_TODO_PHASE_ADVANCED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.TODO_LIFECYCLE,
                meaningful_fields=["slug", "prior_lifecycle_phase", "lifecycle_phase"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.updated",
            description="A workflow todo control-plane field changed and may affect runner eligibility",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_WORKFLOW_TODO_UPDATED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.delivered",
            description="A workflow todo was delivered and may unblock dependents",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_WORKFLOW_TODO_DELIVERED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.roadmap.entry_moved",
            description="A roadmap entry moved between queues or dependency positions",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_WORKFLOW_ROADMAP_ENTRY_MOVED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.planning.todo_finalize_ready",
            description="Finalize-ready worker claim is ready for integration handoff",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PLANNING_TODO_FINALIZE_READY,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key="slug",
                family=LifecycleFamily.PLANNING_READINESS,
                meaningful_fields=["slug", "branch", "sha", "worker_session_id", "ready_at"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.planning.dor_assessed",
            description="Definition of Ready was assessed for a work item",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PLANNING_DOR_ASSESSED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="slug",
                family=LifecycleFamily.PLANNING_READINESS,
                meaningful_fields=["score", "verdict"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.build.completed",
            description="Build phase completed for a work item",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_BUILD_COMPLETED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.BUILD),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.review.verdict_ready",
            description="Code review verdict is ready",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_VERDICT_READY,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.REVIEW, meaningful_fields=["verdict", "round"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.review.needs_decision",
            description="Review requires a human decision before proceeding",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_NEEDS_DECISION,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.REVIEW, meaningful_fields=["question", "round"]
            ),
            actionable=True,
        )
    )

    # --- Deploy events ---

    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deploy.triggered",
            description="Deployment was triggered for a work item",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_TRIGGERED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "environment"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deploy.succeeded",
            description="Deployment completed successfully",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_SUCCEEDED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOY_ATTEMPT),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deploy.failed",
            description="Deployment failed and requires attention",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOY_FAILED,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.DEPLOY_ATTEMPT, meaningful_fields=["error"]
            ),
            actionable=True,
        )
    )

    # --- Ops events ---

    catalog.register(
        EventSchema(
            event_type="domain.sdlc.ops.alert_fired",
            description="An operational alert was triggered",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_OPS_ALERT_FIRED,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["alert_id", "severity"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.ops.alert_resolved",
            description="An operational alert was resolved",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_OPS_ALERT_RESOLVED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(resolves=True, group_key="alert_id", family=LifecycleFamily.OPS_ALERT),
        )
    )

    # --- Maintenance events ---

    catalog.register(
        EventSchema(
            event_type="domain.sdlc.maintenance.dependency_update",
            description="A dependency was updated to a new version",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_MAINTENANCE_DEPENDENCY_UPDATE,
            default_level=EventLevel.OPERATIONAL,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="package",
                family=LifecycleFamily.DEPENDENCY_UPDATE,
                meaningful_fields=["package", "version"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.maintenance.security_patch",
            description="A security patch is required for a dependency",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_MAINTENANCE_SECURITY_PATCH,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["advisory_id", "severity"]),
            actionable=True,
        )
    )

    # --- Prepare lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.input_refined",
            description="Human thinking was captured or updated in input.md",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_INPUT_REFINED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.discovery_started",
            description="Requirements discovery phase dispatched",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_DISCOVERY_STARTED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.requirements_drafted",
            description="Requirements derived from triangulation",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REQUIREMENTS_DRAFTED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.requirements_approved",
            description="Requirements reviewed and approved, ready for plan drafting",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REQUIREMENTS_APPROVED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.plan_drafted",
            description="Implementation plan drafted from approved requirements",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PLAN_DRAFTED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.plan_approved",
            description="Implementation plan reviewed and approved",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PLAN_APPROVED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.completed",
            description="Preparation complete, todo ready for build",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_COMPLETED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.blocked",
            description="Preparation blocked, requires human decision",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_BLOCKED,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["blocker"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.phase_skipped",
            description="Prepare phase skipped via inheritance from parent todo",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_PHASE_SKIPPED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.PREPARE_PIPELINE,
                meaningful_fields=["phase", "reason"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.input_consumed",
            description="Input consumed by discovery worker, requirements production started",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_INPUT_CONSUMED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.artifact_produced",
            description="Prepare artifact written and lifecycle-tracked in state",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_ARTIFACT_PRODUCED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.PREPARE_PIPELINE,
                meaningful_fields=["artifact", "digest"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.artifact_invalidated",
            description="Upstream change cascaded staleness to a prepare artifact",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_ARTIFACT_INVALIDATED,
            default_level=EventLevel.OPERATIONAL,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.PREPARE_PIPELINE,
                meaningful_fields=["stale_artifacts"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.prepare.review_scoped",
            description="Scoped re-review dispatched with a findings artifact",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_PREPARE_REVIEW_SCOPED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.PREPARE_PIPELINE,
                meaningful_fields=["findings_artifact"],
            ),
        )
    )
    # --- Integration lifecycle events ---

    catalog.register(
        EventSchema(
            event_type=IntegrationEventType.STARTED,
            description=_INTEGRATION_STARTED_DESCRIPTION,
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_STARTED,
            default_level=EventLevel.WORKFLOW,
            domain=_SDLC_DOMAIN,
        )
    )
    catalog.register(
        EventSchema(
            event_type=IntegrationEventType.CANDIDATE_DELIVERED,
            description=_INTEGRATION_CANDIDATE_DELIVERED_DESCRIPTION,
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_DELIVERED,
            default_level=EventLevel.WORKFLOW,
            domain=_SDLC_DOMAIN,
        )
    )
    catalog.register(
        EventSchema(
            event_type=IntegrationEventType.CANDIDATE_BLOCKED,
            description=_INTEGRATION_CANDIDATE_BLOCKED_DESCRIPTION,
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_BLOCKED,
            default_level=EventLevel.BUSINESS,
            default_visibility=EventVisibility.LOCAL,
            domain=_SDLC_DOMAIN,
        )
    )
    catalog.register(
        EventSchema(
            event_type=IntegrationEventType.CANDIDATE_PARKED,
            description="An integration candidate was parked for the current drain",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_CANDIDATE_PARKED,
            default_level=EventLevel.BUSINESS,
            default_visibility=EventVisibility.LOCAL,
            domain="sdlc",
        )
    )
    catalog.register(
        EventSchema(
            event_type=IntegrationEventType.DRAIN_COMPLETED,
            description="An integration drain completed with delivered and parked outcomes",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_INTEGRATION_DRAIN_COMPLETED,
            default_level=EventLevel.BUSINESS,
            default_visibility=EventVisibility.LOCAL,
            domain="sdlc",
        )
    )

    catalog.register(
        EventSchema(
            event_type="domain.sdlc.review.approved",
            description="Review passed, candidate eligible for finalization",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_REVIEW_APPROVED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key="slug",
                family=LifecycleFamily.REVIEW_GATE_APPROVED,
                meaningful_fields=["approved_at"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.branch.pushed",
            description="Worktree branch pushed to remote, candidate ready for integration",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_BRANCH_PUSHED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True, group_key="branch", family=LifecycleFamily.BRANCH_PUSHED, meaningful_fields=["pushed_at"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deployment.started",
            description="Finalize ready, candidate queued for integration",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_STARTED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key="slug",
                family=LifecycleFamily.DEPLOYMENT_LIFECYCLE,
                meaningful_fields=["ready_at"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deployment.completed",
            description="Integrated to main, delivery bookkeeping done",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_COMPLETED,
            default_level=EventLevel.WORKFLOW,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_LIFECYCLE
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.sdlc.deployment.failed",
            description="Integration blocked, needs attention",
            subject_assignment=_SUBJECT_ASSIGNMENT_WORKFLOW_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_SDLC_DEPLOYMENT_FAILED,
            default_level=EventLevel.BUSINESS,
            domain="sdlc",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                family=LifecycleFamily.DEPLOYMENT_LIFECYCLE,
                meaningful_fields=["blocked_at"],
            ),
            actionable=True,
        )
    )
