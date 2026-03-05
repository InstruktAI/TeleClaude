"""Event schemas — built-in event type definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_all(catalog: "EventCatalog") -> None:
    from teleclaude_events.schemas.content import register_content
    from teleclaude_events.schemas.deployment import register_deployment
    from teleclaude_events.schemas.node import register_node
    from teleclaude_events.schemas.notification import register_notification
    from teleclaude_events.schemas.schema import register_schema
    from teleclaude_events.schemas.software_development import register_software_development
    from teleclaude_events.schemas.system import register_system

    register_system(catalog)
    register_software_development(catalog)
    register_node(catalog)
    register_deployment(catalog)
    register_content(catalog)
    register_notification(catalog)
    register_schema(catalog)
