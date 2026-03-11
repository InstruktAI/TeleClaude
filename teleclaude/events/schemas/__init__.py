"""Event schemas — built-in event type definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_all(catalog: EventCatalog) -> None:
    from teleclaude.events.schemas.content import register_content
    from teleclaude.events.schemas.creative_production import register_creative_production
    from teleclaude.events.schemas.customer_relations import register_customer_relations
    from teleclaude.events.schemas.deployment import register_deployment
    from teleclaude.events.schemas.marketing import register_marketing
    from teleclaude.events.schemas.node import register_node
    from teleclaude.events.schemas.notification import register_notification
    from teleclaude.events.schemas.schema import register_schema
    from teleclaude.events.schemas.signal import register_signal
    from teleclaude.events.schemas.software_development import register_software_development
    from teleclaude.events.schemas.system import register_system

    register_system(catalog)
    register_software_development(catalog)
    register_marketing(catalog)
    register_creative_production(catalog)
    register_customer_relations(catalog)
    register_node(catalog)
    register_deployment(catalog)
    register_content(catalog)
    register_notification(catalog)
    register_schema(catalog)
    register_signal(catalog)
