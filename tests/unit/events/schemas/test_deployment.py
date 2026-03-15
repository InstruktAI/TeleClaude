"""Characterization tests for teleclaude.events.schemas.deployment."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.deployment import register_deployment

_EXPECTED_TYPES = {
    "deployment.started",
    "deployment.completed",
    "deployment.failed",
    "deployment.rolled_back",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_deployment(catalog)
    return catalog


def test_register_deployment_registers_four_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_deployment_events_have_correct_domain_and_visibility() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "deployment"
        assert schema.default_visibility == EventVisibility.LOCAL


def test_deployment_all_have_slug_sha_idempotency() -> None:
    for schema in _catalog().list_all():
        assert "slug" in schema.idempotency_fields
        assert "sha" in schema.idempotency_fields


def test_deployment_started_creates_lifecycle() -> None:
    schema = _catalog().get("deployment.started")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.meaningful_fields == ["slug"]
    assert schema.default_level == EventLevel.WORKFLOW


def test_deployment_completed_resolves_lifecycle() -> None:
    schema = _catalog().get("deployment.completed")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
    assert schema.lifecycle.group_key == "slug"


def test_deployment_failed_is_actionable_and_business_level() -> None:
    schema = _catalog().get("deployment.failed")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_deployment_rolled_back_resolves() -> None:
    schema = _catalog().get("deployment.rolled_back")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
    assert schema.actionable is False
