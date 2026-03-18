"""Event schemas — built-in event type definitions."""

from __future__ import annotations

from importlib import import_module

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_all(catalog: EventCatalog) -> None:
    """Register every built-in schema group into the provided catalog."""
    registrars = (
        ("teleclaude.events.schemas.system", "register_system"),
        ("teleclaude.events.schemas.software_development", "register_software_development"),
        ("teleclaude.events.schemas.marketing", "register_marketing"),
        ("teleclaude.events.schemas.creative_production", "register_creative_production"),
        ("teleclaude.events.schemas.customer_relations", "register_customer_relations"),
        ("teleclaude.events.schemas.node", "register_node"),
        ("teleclaude.events.schemas.deployment", "register_deployment"),
        ("teleclaude.events.schemas.content", "register_content"),
        ("teleclaude.events.schemas.notification", "register_notification"),
        ("teleclaude.events.schemas.schema", "register_schema"),
        ("teleclaude.events.schemas.signal", "register_signal"),
    )
    for module_name, function_name in registrars:
        registrar = getattr(import_module(module_name), function_name)
        registrar(catalog)
