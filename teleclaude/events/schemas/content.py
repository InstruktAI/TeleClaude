"""Content lifecycle event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_content(catalog: EventCatalog) -> None:
    catalog.register(
        EventSchema(
            event_type="content.dumped",
            description="Raw content was captured and queued for processing",
            default_level=EventLevel.WORKFLOW,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["content_id"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="content.refined",
            description="Content was processed or edited",
            default_level=EventLevel.WORKFLOW,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="content_id"),
        )
    )
    catalog.register(
        EventSchema(
            event_type="content.published",
            description="Content was made available externally",
            default_level=EventLevel.BUSINESS,
            domain="content",
            default_visibility=EventVisibility.LOCAL,
            idempotency_fields=["content_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="content_id"),
        )
    )
