"""Software development domain event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_software_development(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.todo_created",
            description="A new work item was created",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.todo_dumped",
            description="A brain dump was captured for a work item via telec todo dump",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.todo_activated",
            description="A work item moved to active state",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.artifact_changed",
            description="A planning artifact was modified",
            default_level=EventLevel.OPERATIONAL,
            domain="software-development",
            idempotency_fields=["slug", "artifact"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", silent_fields=["artifact", "changed_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.dependency_resolved",
            description="A work item dependency was resolved",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "dependency"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", meaningful_fields=["dependency", "resolved_at"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.planning.dor_assessed",
            description="Definition of Ready was assessed for a work item",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "score"],
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
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.verdict_ready",
            description="Code review verdict is ready",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "round"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["verdict", "round"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.needs_decision",
            description="Review requires a human decision before proceeding",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            idempotency_fields=["slug", "round"],
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
            idempotency_fields=["slug", "environment"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "environment"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deploy.succeeded",
            description="Deployment completed successfully",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "environment"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deploy.failed",
            description="Deployment failed and requires attention",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            idempotency_fields=["slug", "environment"],
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
            idempotency_fields=["alert_id"],
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
            idempotency_fields=["alert_id"],
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
            idempotency_fields=["package", "version"],
            lifecycle=NotificationLifecycle(updates=True, group_key="package", meaningful_fields=["package", "version"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.maintenance.security_patch",
            description="A security patch is required for a dependency",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            idempotency_fields=["advisory_id"],
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
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.triangulation_started",
            description="Two-agent requirements triangulation dispatched",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.requirements_drafted",
            description="Requirements derived from triangulation",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.requirements_approved",
            description="Requirements reviewed and approved, ready for plan drafting",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.plan_drafted",
            description="Implementation plan drafted from approved requirements",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.plan_approved",
            description="Implementation plan reviewed and approved",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.grounding_invalidated",
            description="Preparation artifacts invalidated due to drift",
            default_level=EventLevel.OPERATIONAL,
            domain="software-development",
            idempotency_fields=["slug", "reason"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", meaningful_fields=["reason", "changed_paths"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.regrounded",
            description="Preparation artifacts updated against current truth",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.completed",
            description="Preparation complete, todo ready for build",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.prepare.blocked",
            description="Preparation blocked, requires human decision",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            idempotency_fields=["slug"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="slug", meaningful_fields=["blocker"]
            ),
            actionable=True,
        )
    )

    # --- Integration lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.software-development.review.approved",
            description="Review passed, candidate eligible for finalization",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "review_round"],
            lifecycle=NotificationLifecycle(creates=True, group_key="slug", meaningful_fields=["approved_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.started",
            description="Finalize ready, candidate queued for integration",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "branch", "sha"],
            lifecycle=NotificationLifecycle(creates=True, group_key="slug", meaningful_fields=["ready_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.completed",
            description="Integrated to main, delivery bookkeeping done",
            default_level=EventLevel.WORKFLOW,
            domain="software-development",
            idempotency_fields=["slug", "merge_commit"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.software-development.deployment.failed",
            description="Integration blocked, needs attention",
            default_level=EventLevel.BUSINESS,
            domain="software-development",
            idempotency_fields=["slug", "branch", "sha", "blocked_at"],
            lifecycle=NotificationLifecycle(updates=True, group_key="slug", meaningful_fields=["blocked_at"]),
            actionable=True,
        )
    )
