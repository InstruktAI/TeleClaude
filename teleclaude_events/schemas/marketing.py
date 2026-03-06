"""Marketing domain event schemas.

Covers three event categories:

- **content**: Content lifecycle from brief through draft, publish, and performance reporting.
- **campaign**: Campaign management including launch, budget monitoring, and reporting.
- **feed**: Signal pipeline bridge — wraps signal synthesis output as domain-level feed events
  for downstream marketing automation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude_events.catalog import EventSchema, NotificationLifecycle
from teleclaude_events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_marketing(catalog: "EventCatalog") -> None:
    # --- Content events ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.brief_created",
            description="A content brief was created, kicking off the content lifecycle",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["content_id", "title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.draft_ready",
            description="A content draft is ready for review",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="content_id", meaningful_fields=["title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.published",
            description="Content was published",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="content_id"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.content.performance_reported",
            description="Content performance metrics were reported",
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            idempotency_fields=["content_id", "period"],
            lifecycle=NotificationLifecycle(updates=True, group_key="content_id", silent_fields=["metrics"]),
        )
    )

    # --- Campaign events ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.launched",
            description="A marketing campaign was launched",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["campaign_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["campaign_id", "name"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.budget_threshold_hit",
            description="Campaign spend crossed a budget threshold requiring attention",
            default_level=EventLevel.BUSINESS,
            domain="marketing",
            idempotency_fields=["campaign_id", "threshold"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="campaign_id", meaningful_fields=["spent", "threshold"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.ended",
            description="A marketing campaign ended",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["campaign_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="campaign_id"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.campaign.report_ready",
            description="Post-campaign performance report is ready",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["campaign_id", "report_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["campaign_id", "report_id"]),
        )
    )

    # --- Feed events (signal pipeline bridge) ---

    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.signal_received",
            description="Raw signal input received from the feed monitor",
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            idempotency_fields=["signal_id"],
            lifecycle=NotificationLifecycle(creates=True, silent_fields=["raw"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.cluster_formed",
            description="Signals were clustered into a topic cluster",
            default_level=EventLevel.OPERATIONAL,
            domain="marketing",
            idempotency_fields=["cluster_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["cluster_id", "topic"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.marketing.feed.synthesis_ready",
            description="Signal synthesis output is ready for marketing review",
            default_level=EventLevel.WORKFLOW,
            domain="marketing",
            idempotency_fields=["synthesis_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["synthesis_id", "summary"]),
            actionable=True,
        )
    )
