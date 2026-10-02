"""Deployment lifecycle event schemas."""

from __future__ import annotations

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


_SUBJECT_ASSIGNMENT_DEPLOYMENT_PROJECT = SubjectAssignment(
    kinds=[EventHomeKind.PROJECT], about="the project being deployed"
)
_PAYLOAD_FIELDS_DEPLOYMENT_COMPLETED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DEPLOYMENT_FAILED: list[PayloadField] = [
    PayloadField(name="reason", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DEPLOYMENT_ROLLED_BACK: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DEPLOYMENT_STARTED: list[PayloadField] = [
    PayloadField(name="slug", kind=PayloadValueKind.ANY, nullable=True),
]


def register_deployment(catalog: EventCatalog) -> None:
    """Register deployment lifecycle event schemas."""
    catalog.register(
        EventSchema(
            event_type="deployment.started",
            description="Deployment initiated",
            subject_assignment=_SUBJECT_ASSIGNMENT_DEPLOYMENT_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DEPLOYMENT_STARTED,
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.completed",
            description="Deployment succeeded",
            subject_assignment=_SUBJECT_ASSIGNMENT_DEPLOYMENT_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DEPLOYMENT_COMPLETED,
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_OUTCOME),
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.failed",
            description="Deployment failed and requires attention",
            subject_assignment=_SUBJECT_ASSIGNMENT_DEPLOYMENT_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DEPLOYMENT_FAILED,
            default_level=EventLevel.BUSINESS,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "reason"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="deployment.rolled_back",
            description="Rollback executed after deployment failure",
            subject_assignment=_SUBJECT_ASSIGNMENT_DEPLOYMENT_PROJECT,
            payload_fields=_PAYLOAD_FIELDS_DEPLOYMENT_ROLLED_BACK,
            default_level=EventLevel.WORKFLOW,
            domain="deployment",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_OUTCOME),
        )
    )
