"""Characterization tests for teleclaude.events.schemas.notification."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.notification import register_notification

_EXPECTED_TYPES = {
    "notification.escalation",
    "notification.resolution",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_notification(catalog)
    return catalog


def test_register_notification_registers_two_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_notification_events_have_local_visibility() -> None:
    for schema in _catalog().list_all():
        assert schema.default_visibility == EventVisibility.LOCAL


def test_all_notification_events_have_notification_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "notification"


def test_notification_escalation_is_actionable_and_business_level() -> None:
    schema = _catalog().get("notification.escalation")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_notification_escalation_creates_lifecycle() -> None:
    schema = _catalog().get("notification.escalation")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.meaningful_fields == ["escalation_id", "reason"]


def test_notification_resolution_resolves_lifecycle() -> None:
    schema = _catalog().get("notification.resolution")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
    assert schema.lifecycle.group_key == "escalation_id"
    assert schema.default_level == EventLevel.WORKFLOW


def test_both_events_have_escalation_id_idempotency() -> None:
    for schema in _catalog().list_all():
        assert "escalation_id" in schema.idempotency_fields
