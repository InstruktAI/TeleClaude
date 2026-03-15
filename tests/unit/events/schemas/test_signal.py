"""Characterization tests for teleclaude.events.schemas.signal."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.signal import register_signal

_EXPECTED_TYPES = {
    "signal.ingest.received",
    "signal.cluster.formed",
    "signal.synthesis.ready",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_signal(catalog)
    return catalog


def test_register_signal_registers_three_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_signal_events_have_local_visibility() -> None:
    for schema in _catalog().list_all():
        assert schema.default_visibility == EventVisibility.LOCAL


def test_all_signal_events_have_signal_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "signal"


def test_signal_ingest_received_has_no_lifecycle() -> None:
    schema = _catalog().get("signal.ingest.received")
    assert schema is not None
    assert schema.lifecycle is None
    assert schema.actionable is False
    assert schema.default_level == EventLevel.OPERATIONAL


def test_signal_ingest_received_idempotency_fields() -> None:
    schema = _catalog().get("signal.ingest.received")
    assert schema is not None
    assert schema.idempotency_fields == ["source_id", "item_url"]


def test_signal_cluster_formed_has_no_lifecycle() -> None:
    schema = _catalog().get("signal.cluster.formed")
    assert schema is not None
    assert schema.lifecycle is None
    assert schema.actionable is False
    assert schema.default_level == EventLevel.OPERATIONAL


def test_signal_synthesis_ready_is_actionable_with_lifecycle() -> None:
    schema = _catalog().get("signal.synthesis.ready")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.WORKFLOW
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert "synthesis" in schema.lifecycle.meaningful_fields
