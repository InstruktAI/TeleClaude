"""Creative production domain event schemas.

Covers two event categories:

- **asset**: Asset lifecycle from brief through draft, review, revision, approval, and delivery.
- **format**: Format conversion/transcode lifecycle for multi-format asset delivery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_creative_production(catalog: EventCatalog) -> None:
    # --- Asset lifecycle events ---

    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.brief_created",
            description="A creative asset brief was created",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["asset_id", "title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.draft_submitted",
            description="A creative asset draft was submitted for review",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="asset_id", meaningful_fields=["title"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.review_requested",
            description="Review was requested for a creative asset",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="asset_id", meaningful_fields=["reviewer", "deadline"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.revision_requested",
            description="Revisions were requested for a creative asset",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="asset_id", meaningful_fields=["feedback"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.approved",
            description="A creative asset was approved",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="asset_id", meaningful_fields=["approved_by"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.asset.delivered",
            description="A creative asset was delivered to the client or destination",
            default_level=EventLevel.WORKFLOW,
            domain="creative-production",
            idempotency_fields=["asset_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="asset_id"),
        )
    )

    # --- Format/transcode events ---

    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_started",
            description="Format transcoding started for an asset",
            default_level=EventLevel.OPERATIONAL,
            domain="creative-production",
            idempotency_fields=["asset_id", "format"],
            lifecycle=NotificationLifecycle(creates=True, silent_fields=["job_id"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_completed",
            description="Format transcoding completed for an asset",
            default_level=EventLevel.OPERATIONAL,
            domain="creative-production",
            idempotency_fields=["asset_id", "format"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="asset_id"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.creative-production.format.transcode_failed",
            description="Format transcoding failed and requires attention",
            default_level=EventLevel.BUSINESS,
            domain="creative-production",
            idempotency_fields=["asset_id", "format"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="asset_id", meaningful_fields=["error", "format"]
            ),
            actionable=True,
        )
    )
