"""Marketing domain event schemas.

Covers three event categories:

- **content**: Content lifecycle from brief through draft, publish, and performance reporting.
- **campaign**: Campaign management including launch, budget monitoring, and reporting.
- **feed**: Signal pipeline bridge — wraps signal synthesis output as domain-level feed events
  for downstream marketing automation.
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


_SUBJECT_ASSIGNMENT_MARKETING_COMPANY = SubjectAssignment(
    kinds=[EventHomeKind.COMPANY], about="the company whose marketing activity this event records"
)
_SUBJECT_ASSIGNMENT_MARKETING_FEED = SubjectAssignment(
    kinds=[], about="the signal event bridged into the marketing feed"
)
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_BUDGET_THRESHOLD_HIT: list[PayloadField] = [
    PayloadField(name="campaign_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="spent", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="threshold", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_ENDED: list[PayloadField] = [
    PayloadField(name="campaign_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_LAUNCHED: list[PayloadField] = [
    PayloadField(name="campaign_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="name", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_REPORT_READY: list[PayloadField] = [
    PayloadField(name="campaign_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="report_id", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_BRIEF_CREATED: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="title", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_DRAFT_READY: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="title", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_PERFORMANCE_REPORTED: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=False),
    PayloadField(name="metrics", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_PUBLISHED: list[PayloadField] = [
    PayloadField(name="content_id", kind=PayloadValueKind.ANY, nullable=False),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_CLUSTER_FORMED: list[PayloadField] = [
    PayloadField(name="cluster_id", kind=PayloadValueKind.ANY, nullable=True),
    PayloadField(name="topic", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_SIGNAL_RECEIVED: list[PayloadField] = [
    PayloadField(name="raw", kind=PayloadValueKind.ANY, nullable=True),
]
_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_SYNTHESIS_READY: list[PayloadField] = [
    PayloadField(name="source_event", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="summary", kind=PayloadValueKind.STRING, nullable=False),
    PayloadField(name="synthesis_id", kind=PayloadValueKind.STRING, nullable=False),
]


def register_marketing(catalog: EventCatalog) -> None:
    """Register marketing-domain event schemas."""
    # --- Content events ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.brief_created",
            description="A content brief was created, kicking off the content lifecycle",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_BRIEF_CREATED,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["content_id", "title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.draft_ready",
            description="A content draft is ready for review",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_DRAFT_READY,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="content_id",
                family=LifecycleFamily.MARKETING_CONTENT_LIFECYCLE,
                meaningful_fields=["title"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.published",
            description="Content was published",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_PUBLISHED,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="content_id", family=LifecycleFamily.MARKETING_CONTENT_LIFECYCLE
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.performance_reported",
            description="Content performance metrics were reported",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CONTENT_PERFORMANCE_REPORTED,
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="content_id",
                family=LifecycleFamily.MARKETING_CONTENT_LIFECYCLE,
                silent_fields=["metrics"],
            ),
        )
    )

    # --- Campaign events ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.launched",
            description="A marketing campaign was launched",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_LAUNCHED,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["campaign_id", "name"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.budget_threshold_hit",
            description="Campaign spend crossed a budget threshold requiring attention",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_BUDGET_THRESHOLD_HIT,
            default_level=EventLevel.BUSINESS,
            domain="marketing",
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="campaign_id",
                family=LifecycleFamily.MARKETING_CAMPAIGN,
                meaningful_fields=["spent", "threshold"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.ended",
            description="A marketing campaign ended",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_ENDED,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(
                resolves=True, group_key="campaign_id", family=LifecycleFamily.MARKETING_CAMPAIGN
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.report_ready",
            description="Post-campaign performance report is ready",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_COMPANY,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_CAMPAIGN_REPORT_READY,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["campaign_id", "report_id"]),
        )
    )

    # --- Feed events (signal pipeline bridge) ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.signal_received",
            description="Raw signal input received from the feed monitor",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_FEED,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_SIGNAL_RECEIVED,
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, silent_fields=["raw"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.cluster_formed",
            description="Signals were clustered into a topic cluster",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_FEED,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_CLUSTER_FORMED,
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["cluster_id", "topic"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.synthesis_ready",
            description="Signal synthesis output is ready for marketing review",
            subject_assignment=_SUBJECT_ASSIGNMENT_MARKETING_FEED,
            payload_fields=_PAYLOAD_FIELDS_DOMAIN_MARKETING_FEED_SYNTHESIS_READY,
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["synthesis_id", "summary"]),
            actionable=True,
        )
    )
