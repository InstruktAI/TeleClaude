"""Tests for Task 8: new prepare lifecycle events registered in catalog."""

from __future__ import annotations

NEW_EVENTS = [
    "domain.software-development.prepare.phase_skipped",
    "domain.software-development.prepare.input_consumed",
    "domain.software-development.prepare.artifact_produced",
    "domain.software-development.prepare.artifact_invalidated",
    "domain.software-development.prepare.finding_recorded",
    "domain.software-development.prepare.finding_resolved",
    "domain.software-development.prepare.review_scoped",
    "domain.software-development.prepare.split_inherited",
]


def test_new_prepare_events_registered() -> None:
    """All 8 new prepare lifecycle events are registered in the event catalog."""
    from teleclaude.events.catalog import EventCatalog
    from teleclaude.events.schemas.software_development import register_software_development

    catalog = EventCatalog()
    register_software_development(catalog)

    for event_type in NEW_EVENTS:
        assert catalog.get(event_type) is not None, f"Event '{event_type}' not found in catalog after registration"
