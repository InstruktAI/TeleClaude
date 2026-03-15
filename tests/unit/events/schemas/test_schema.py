"""Characterization tests for teleclaude.events.schemas.schema."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.schema import register_schema

_EXPECTED_TYPES = {
    "schema.proposed",
    "schema.adopted",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_schema(catalog)
    return catalog


def test_register_schema_registers_two_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_schema_events_have_cluster_visibility() -> None:
    for schema in _catalog().list_all():
        assert schema.default_visibility == EventVisibility.CLUSTER


def test_all_schema_events_have_schema_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "schema"


def test_all_schema_events_have_operational_level() -> None:
    for schema in _catalog().list_all():
        assert schema.default_level == EventLevel.OPERATIONAL


def test_all_schema_events_have_no_lifecycle() -> None:
    for schema in _catalog().list_all():
        assert schema.lifecycle is None


def test_all_schema_events_are_not_actionable() -> None:
    for schema in _catalog().list_all():
        assert schema.actionable is False


def test_schema_idempotency_includes_version() -> None:
    for schema in _catalog().list_all():
        assert "schema_id" in schema.idempotency_fields
        assert "version" in schema.idempotency_fields
