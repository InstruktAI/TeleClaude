"""Creative production domain event schemas.

Covers two event categories:

- **asset**: Asset lifecycle from brief through draft, review, revision, approval, and delivery.
- **format**: Format conversion/transcode lifecycle for multi-format asset delivery.
"""

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
from teleclaude.events.envelope import EventHomeKind, EventLevel

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY = SubjectAssignment(
    kinds=[EventHomeKind.COMPANY], about="the company whose creative production activity this event records"
)
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_APPROVED: list[PayloadField] = [
    PayloadField(name="approved_by", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_BRIEF_CREATED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="title", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_DELIVERED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_DRAFT_SUBMITTED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="title", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_REVIEW_REQUESTED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="deadline", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="reviewer", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_REVISION_REQUESTED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="feedback", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_COMPLETED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_FAILED: list[PayloadField] = [
    PayloadField(name="asset_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="error", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="format", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_STARTED: list[PayloadField] = [
    PayloadField(name="job_id", kind=PayloadValueKind.ANY, nullable=True),
]


def register_creative_production(catalog: EventCatalog) -> None:
    """Register creative production domain event schemas."""
    # --- Asset lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.brief_created",
            description="A creative asset brief was created",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_BRIEF_CREATED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["asset_id", "title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.draft_submitted",
            description="A creative asset draft was submitted for review",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_DRAFT_SUBMITTED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="asset_id",
                family=LifecycleFamily.CREATIVE_ASSET_REVIEW,
                meaningful_fields=["title"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.review_requested",
            description="Review was requested for a creative asset",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_REVIEW_REQUESTED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="asset_id",
                family=LifecycleFamily.CREATIVE_ASSET_REVIEW,
                meaningful_fields=["reviewer", "deadline"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.revision_requested",
            description="Revisions were requested for a creative asset",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_REVISION_REQUESTED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="asset_id",
                family=LifecycleFamily.CREATIVE_ASSET_REVIEW,
                meaningful_fields=["feedback"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.approved",
            description="A creative asset was approved",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_APPROVED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="asset_id",
                family=LifecycleFamily.CREATIVE_ASSET_REVIEW,
                meaningful_fields=["approved_by"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.delivered",
            description="A creative asset was delivered to the client or destination",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_ASSET_DELIVERED,
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="asset_id", family=LifecycleFamily.CREATIVE_ASSET_REVIEW
            ),
        )
    )

    # --- Format/transcode events ---

    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_started",
            description="Format transcoding started for an asset",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_STARTED,
            default_level=EventLevel.OPERATIONAL,
            domain="creative-production",
            lifecycle=NotificationLifecycle(creates=True, silent_fields=["job_id"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_completed",
            description="Format transcoding completed for an asset",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_COMPLETED,
            default_level=EventLevel.OPERATIONAL,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="asset_id", family=LifecycleFamily.CREATIVE_ASSET_TRANSCODE
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_failed",
            description="Format transcoding failed and requires attention",
            subject_assignment=_SUBJECT_ASSIGNMENT_CREATIVE_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_CREATIVE_PRODUCTION_FORMAT_TRANSCODE_FAILED,
            default_level=EventLevel.BUSINESS,
            domain="creative-production",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="asset_id",
                family=LifecycleFamily.CREATIVE_ASSET_TRANSCODE,
                meaningful_fields=["error", "format"],
            ),
            actionable=True,
        )
    )
