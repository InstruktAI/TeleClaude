"""Characterization tests for teleclaude.events.schemas.node."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.node import register_node

_EXPECTED_TYPES = {
    "node.alive",
    "node.leaving",
    "node.descriptor_updated",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_node(catalog)
    return catalog


def test_register_node_registers_three_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_node_events_have_cluster_visibility() -> None:
    for schema in _catalog().list_all():
        assert schema.default_visibility == EventVisibility.CLUSTER


def test_all_node_events_have_node_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "node"


def test_node_alive_has_infrastructure_level() -> None:
    schema = _catalog().get("node.alive")
    assert schema is not None
    assert schema.default_level == EventLevel.INFRASTRUCTURE


def test_node_leaving_has_infrastructure_level() -> None:
    schema = _catalog().get("node.leaving")
    assert schema is not None
    assert schema.default_level == EventLevel.INFRASTRUCTURE


def test_node_descriptor_updated_has_operational_level() -> None:
    schema = _catalog().get("node.descriptor_updated")
    assert schema is not None
    assert schema.default_level == EventLevel.OPERATIONAL


def test_node_events_have_node_id_idempotency() -> None:
    for schema in _catalog().list_all():
        assert schema.idempotency_fields == ["node_id"]


def test_node_events_have_no_lifecycle() -> None:
    for schema in _catalog().list_all():
        assert schema.lifecycle is None


def test_node_events_are_not_actionable() -> None:
    for schema in _catalog().list_all():
        assert schema.actionable is False
