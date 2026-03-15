"""Characterization tests for teleclaude.events.schemas.creative_production."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel
from teleclaude.events.schemas.creative_production import register_creative_production

_EXPECTED_TYPES = {
    "domain.creative-production.asset.brief_created",
    "domain.creative-production.asset.draft_submitted",
    "domain.creative-production.asset.review_requested",
    "domain.creative-production.asset.revision_requested",
    "domain.creative-production.asset.approved",
    "domain.creative-production.asset.delivered",
    "domain.creative-production.format.transcode_started",
    "domain.creative-production.format.transcode_completed",
    "domain.creative-production.format.transcode_failed",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_creative_production(catalog)
    return catalog


def test_register_creative_production_registers_nine_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_creative_production_events_have_correct_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "creative-production"


def test_asset_brief_created_creates_lifecycle() -> None:
    schema = _catalog().get("domain.creative-production.asset.brief_created")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.meaningful_fields == ["asset_id", "title"]


def test_asset_review_requested_is_actionable() -> None:
    schema = _catalog().get("domain.creative-production.asset.review_requested")
    assert schema is not None
    assert schema.actionable is True


def test_asset_delivered_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.creative-production.asset.delivered")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
    assert schema.lifecycle.group_key == "asset_id"


def test_format_transcode_events_have_operational_or_business_level() -> None:
    catalog = _catalog()
    started = catalog.get("domain.creative-production.format.transcode_started")
    completed = catalog.get("domain.creative-production.format.transcode_completed")
    failed = catalog.get("domain.creative-production.format.transcode_failed")
    assert started is not None and started.default_level == EventLevel.OPERATIONAL
    assert completed is not None and completed.default_level == EventLevel.OPERATIONAL
    assert failed is not None and failed.default_level == EventLevel.BUSINESS


def test_transcode_failed_is_actionable() -> None:
    schema = _catalog().get("domain.creative-production.format.transcode_failed")
    assert schema is not None
    assert schema.actionable is True


def test_transcode_started_idempotency_fields_include_format() -> None:
    schema = _catalog().get("domain.creative-production.format.transcode_started")
    assert schema is not None
    assert schema.idempotency_fields == ["asset_id", "format"]
