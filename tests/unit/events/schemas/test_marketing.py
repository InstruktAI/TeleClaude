"""Characterization tests for teleclaude.events.schemas.marketing."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel
from teleclaude.events.schemas.marketing import register_marketing

_EXPECTED_TYPES = {
    "domain.marketing.content.brief_created",
    "domain.marketing.content.draft_ready",
    "domain.marketing.content.published",
    "domain.marketing.content.performance_reported",
    "domain.marketing.campaign.launched",
    "domain.marketing.campaign.budget_threshold_hit",
    "domain.marketing.campaign.ended",
    "domain.marketing.campaign.report_ready",
    "domain.marketing.feed.signal_received",
    "domain.marketing.feed.cluster_formed",
    "domain.marketing.feed.synthesis_ready",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_marketing(catalog)
    return catalog


def test_register_marketing_registers_eleven_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_marketing_events_have_correct_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "marketing"


def test_campaign_budget_threshold_hit_is_actionable() -> None:
    schema = _catalog().get("domain.marketing.campaign.budget_threshold_hit")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_campaign_budget_threshold_idempotency_includes_threshold() -> None:
    schema = _catalog().get("domain.marketing.campaign.budget_threshold_hit")
    assert schema is not None
    assert "threshold" in schema.idempotency_fields
    assert "campaign_id" in schema.idempotency_fields


def test_feed_synthesis_ready_is_actionable() -> None:
    schema = _catalog().get("domain.marketing.feed.synthesis_ready")
    assert schema is not None
    assert schema.actionable is True


def test_content_brief_created_creates_lifecycle() -> None:
    schema = _catalog().get("domain.marketing.content.brief_created")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True


def test_content_published_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.marketing.content.published")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True


def test_campaign_ended_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.marketing.campaign.ended")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True


def test_performance_reported_has_operational_level() -> None:
    schema = _catalog().get("domain.marketing.content.performance_reported")
    assert schema is not None
    assert schema.default_level == EventLevel.OPERATIONAL
