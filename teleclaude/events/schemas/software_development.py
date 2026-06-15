"""Software development domain event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_software_development(catalog: EventCatalog) -> None:
    """Register software-development domain event schemas."""
    catalog.register(
        EventSchema(
            event_type="workflow.todo.created",
            description="A workflow todo was created and may require lifecycle-runner evaluation",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, group_key="slug", meaningful_fields=["slug", "kind"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.phase_advanced",
            description="A workflow todo advanced lifecycle phase and may unblock runner work",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="slug",
                meaningful_fields=["slug", "prior_lifecycle_phase", "lifecycle_phase"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.updated",
            description="A workflow todo control-plane field changed and may affect runner eligibility",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.todo.delivered",
            description="A workflow todo was delivered and may unblock dependents",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="workflow.roadmap.entry_moved",
            description="A roadmap entry moved between queues or dependency positions",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.todo_finalize_ready",
            description="Finalize-ready worker claim is ready for integration handoff",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(
                creates=True,
                group_key="slug",
                meaningful_fields=["slug", "branch", "sha", "worker_session_id", "ready_at"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.dor_assessed",
            description="Definition of Ready was assessed for a work item",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(
                creates=True, updates=True, group_key="slug", meaningful_fields=["score", "verdict"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.build.completed",
            description="Build phase completed for a work item",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.verdict_ready",
            description="Code review verdict is ready",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["verdict", "round"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.needs_decision",
            description="Review requires a human decision before proceeding",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["question", "round"]),
            actionable=True,
        )
    )

    # --- Deploy events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.deploy.triggered",
            description="Deployment was triggered for a work item",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "environment"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deploy.succeeded",
            description="Deployment completed successfully",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deploy.failed",
            description="Deployment failed and requires attention",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["error"]),
            actionable=True,
        )
    )

    # --- Ops events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.ops.alert_fired",
            description="An operational alert was triggered",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["alert_id", "severity"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.ops.alert_resolved",
            description="An operational alert was resolved",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="alert_id"),
        )
    )

    # --- Maintenance events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.maintenance.dependency_update",
            description="A dependency was updated to a new version",
            default_level=EventLevel.OPERATIONAL,
            domain="software-development",
            lifecycle=NotificationLifecycle(
                updates=True, group_key="package", meaningful_fields=["package", "version"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.maintenance.security_patch",
            description="A security patch is required for a dependency",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["advisory_id", "severity"]),
            actionable=True,
        )
    )

    # --- Prepare lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.input_refined",
            description="Human thinking was captured or updated in input.md",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.discovery_started",
            description="Requirements discovery phase dispatched",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.requirements_drafted",
            description="Requirements derived from triangulation",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.requirements_approved",
            description="Requirements reviewed and approved, ready for plan drafting",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.plan_drafted",
            description="Implementation plan drafted from approved requirements",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.plan_approved",
            description="Implementation plan reviewed and approved",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.completed",
            description="Preparation complete, todo ready for build",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.blocked",
            description="Preparation blocked, requires human decision",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["blocker"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.phase_skipped",
            description="Prepare phase skipped via inheritance from parent todo",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["phase", "reason"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.input_consumed",
            description="Input consumed by discovery worker, requirements production started",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.artifact_produced",
            description="Prepare artifact written and lifecycle-tracked in state",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["artifact", "digest"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.artifact_invalidated",
            description="Upstream change cascaded staleness to a prepare artifact",
            default_level=EventLevel.OPERATIONAL,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["stale_artifacts"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.review_scoped",
            description="Scoped re-review dispatched with a findings artifact",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["findings_artifact"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.split_inherited",
            description="Child todo inherited parent approved prepare phase on split",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(
                creates=True, group_key="child_slug", meaningful_fields=["inherited_phase"]
            ),
        )
    )

    # --- Integration lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.approved",
            description="Review passed, candidate eligible for finalization",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, group_key="slug", meaningful_fields=["approved_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.branch.pushed",
            description="Worktree branch pushed to remote, candidate ready for integration",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, group_key="branch", meaningful_fields=["pushed_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.started",
            description="Finalize ready, candidate queued for integration",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(creates=True, group_key="slug", meaningful_fields=["ready_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.completed",
            description="Integrated to main, delivery bookkeeping done",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.failed",
            description="Integration blocked, needs attention",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["blocked_at"]),
            actionable=True,
        )
    )
