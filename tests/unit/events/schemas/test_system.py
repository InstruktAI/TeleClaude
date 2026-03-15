"""Characterization tests for teleclaude.events.schemas.system."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.system import register_system

_EXPECTED_TYPES = {
    "system.daemon.restarted",
    "system.worker.crashed",
    "system.burst.detected",
    "system.failure_cascade.detected",
    "system.entity.degraded",
    "system.sandbox-container.unhealthy",
    "system.sandbox-container.docker-unavailable",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_system(catalog)
    return catalog


def test_register_system_registers_seven_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_system_events_have_system_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "system"


def test_daemon_restarted_has_cluster_visibility_and_infrastructure_level() -> None:
    schema = _catalog().get("system.daemon.restarted")
    assert schema is not None
    assert schema.default_visibility == EventVisibility.CLUSTER
    assert schema.default_level == EventLevel.INFRASTRUCTURE


def test_worker_crashed_is_actionable() -> None:
    schema = _catalog().get("system.worker.crashed")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.OPERATIONAL


def test_failure_cascade_detected_is_actionable_and_business_level() -> None:
    schema = _catalog().get("system.failure_cascade.detected")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS
    assert schema.default_visibility == EventVisibility.CLUSTER


def test_entity_degraded_creates_and_updates_lifecycle() -> None:
    schema = _catalog().get("system.entity.degraded")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.updates is True
    assert schema.lifecycle.group_key == "entity"


def test_sandbox_container_events_have_empty_idempotency() -> None:
    catalog = _catalog()
    for event_type in ("system.sandbox-container.unhealthy", "system.sandbox-container.docker-unavailable"):
        schema = catalog.get(event_type)
        assert schema is not None
        assert schema.idempotency_fields == []


def test_sandbox_events_are_not_actionable() -> None:
    catalog = _catalog()
    for event_type in ("system.sandbox-container.unhealthy", "system.sandbox-container.docker-unavailable"):
        schema = catalog.get(event_type)
        assert schema is not None
        assert schema.actionable is False


def test_burst_detected_has_local_visibility() -> None:
    schema = _catalog().get("system.burst.detected")
    assert schema is not None
    assert schema.default_visibility == EventVisibility.LOCAL
    assert schema.actionable is False
