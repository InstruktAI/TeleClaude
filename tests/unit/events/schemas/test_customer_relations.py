"""Characterization tests for teleclaude.events.schemas.customer_relations."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel
from teleclaude.events.schemas.customer_relations import register_customer_relations

_EXPECTED_TYPES = {
    "domain.customer-relations.helpdesk.ticket_created",
    "domain.customer-relations.helpdesk.ticket_updated",
    "domain.customer-relations.helpdesk.ticket_escalated",
    "domain.customer-relations.helpdesk.ticket_resolved",
    "domain.customer-relations.satisfaction.survey_sent",
    "domain.customer-relations.satisfaction.response_received",
    "domain.customer-relations.satisfaction.score_recorded",
    "domain.customer-relations.escalation.triggered",
    "domain.customer-relations.escalation.acknowledged",
    "domain.customer-relations.escalation.resolved",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_customer_relations(catalog)
    return catalog


def test_register_customer_relations_registers_ten_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_customer_relations_events_have_correct_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "customer-relations"


def test_ticket_escalated_is_actionable_and_business_level() -> None:
    schema = _catalog().get("domain.customer-relations.helpdesk.ticket_escalated")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_ticket_resolved_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.customer-relations.helpdesk.ticket_resolved")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True


def test_ticket_created_creates_lifecycle() -> None:
    schema = _catalog().get("domain.customer-relations.helpdesk.ticket_created")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.meaningful_fields == ["ticket_id", "subject"]


def test_escalation_triggered_is_actionable() -> None:
    schema = _catalog().get("domain.customer-relations.escalation.triggered")
    assert schema is not None
    assert schema.actionable is True
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True


def test_satisfaction_response_received_idempotency_has_respondent() -> None:
    schema = _catalog().get("domain.customer-relations.satisfaction.response_received")
    assert schema is not None
    assert "respondent_id" in schema.idempotency_fields
    assert "survey_id" in schema.idempotency_fields


def test_satisfaction_score_recorded_resolves() -> None:
    schema = _catalog().get("domain.customer-relations.satisfaction.score_recorded")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
