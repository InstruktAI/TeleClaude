"""Customer relations domain event schemas.

Covers three event categories with strict trust controls:

- **helpdesk**: Help desk ticket lifecycle from creation through escalation and resolution.
- **satisfaction**: Customer satisfaction survey and score tracking.
- **escalation**: Explicit escalation pathway with acknowledgment and resolution tracking.

All actionable events in this domain require human confirmation (trust_threshold: strict).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_customer_relations(catalog: EventCatalog) -> None:
    # --- Help desk events ---

    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.helpdesk.ticket_created",
            description="A new help desk ticket was created",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["ticket_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["ticket_id", "subject"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.helpdesk.ticket_updated",
            description="A help desk ticket was updated",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["ticket_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="ticket_id", silent_fields=["updated_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.helpdesk.ticket_escalated",
            description="A help desk ticket was escalated and requires immediate attention",
            default_level=EventLevel.BUSINESS,
            domain="customer-relations",
            idempotency_fields=["ticket_id"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="ticket_id", meaningful_fields=["reason", "escalated_to"]
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.helpdesk.ticket_resolved",
            description="A help desk ticket was resolved",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["ticket_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="ticket_id"),
        )
    )

    # --- Satisfaction events ---

    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.satisfaction.survey_sent",
            description="A customer satisfaction survey was sent",
            default_level=EventLevel.OPERATIONAL,
            domain="customer-relations",
            idempotency_fields=["survey_id"],
            lifecycle=NotificationLifecycle(creates=True, silent_fields=["sent_at"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.satisfaction.response_received",
            description="A customer satisfaction survey response was received",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["survey_id", "respondent_id"],
            lifecycle=NotificationLifecycle(updates=True, group_key="survey_id", meaningful_fields=["score"]),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.satisfaction.score_recorded",
            description="Customer satisfaction score was aggregated and recorded",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["survey_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="survey_id"),
        )
    )

    # --- Escalation events ---

    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.escalation.triggered",
            description="An escalation was triggered requiring human decision",
            default_level=EventLevel.BUSINESS,
            domain="customer-relations",
            idempotency_fields=["escalation_id"],
            lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["escalation_id", "reason"]),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.escalation.acknowledged",
            description="An escalation was acknowledged by a team member",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["escalation_id"],
            lifecycle=NotificationLifecycle(
                updates=True, group_key="escalation_id", meaningful_fields=["acknowledged_by"]
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="domain.customer-relations.escalation.resolved",
            description="An escalation was resolved",
            default_level=EventLevel.WORKFLOW,
            domain="customer-relations",
            idempotency_fields=["escalation_id"],
            lifecycle=NotificationLifecycle(resolves=True, group_key="escalation_id"),
        )
    )
