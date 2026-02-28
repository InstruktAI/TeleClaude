"""Event schemas — built-in event type definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude_events.catalog import EventCatalog


def register_all(catalog: "EventCatalog") -> None:
    from teleclaude_events.schemas.software_development import register_software_development
    from teleclaude_events.schemas.system import register_system

    register_system(catalog)
    register_software_development(catalog)
