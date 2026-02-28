"""Software development domain event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel, EventVisibility

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
            description="A work item was deferred/discarded",
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
