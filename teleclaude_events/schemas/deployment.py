"""Deployment lifecycle event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_deployment(catalog: "EventCatalog") -> None:
    catalog.register(
        EventSchema(
            event_type="deployment.started",
            description="Deployment initiated",
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["slug", "sha"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.completed",
            description="Deployment succeeded",
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["slug", "sha"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.failed",
            description="Deployment failed and requires attention",
            default_level=EventLevel.BUSINESS,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["slug", "sha"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "reason"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.rolled_back",
            description="Rollback executed after deployment failure",
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["slug", "sha"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug"),
        )
    )
