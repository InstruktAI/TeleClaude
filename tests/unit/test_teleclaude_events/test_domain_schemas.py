"""Tests for domain pillar event schema registration."""

from __future__ import annotations

from teleclaude_events.catalog import EventCatalog, build_default_catalog
from teleclaude_events.schemas.creative_production import register_creative_production
from teleclaude_events.schemas.customer_relations import register_customer_relations
from teleclaude_events.schemas.marketing import register_marketing
from teleclaude_events.schemas.software_development import register_software_development


class TestSoftwareDevelopmentSchemas:
    def test_original_nine_events_preserved(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        original = [
            "domain.software-development.planning.todo_created",
            "domain.software-development.planning.todo_dumped",
            "domain.software-development.planning.todo_activated",
            "domain.software-development.planning.artifact_changed",
            "domain.software-development.planning.dependency_resolved",
            "domain.software-development.planning.dor_assessed",
            "domain.software-development.build.completed",
            "domain.software-development.review.verdict_ready",
            "domain.software-development.review.needs_decision",
        ]
        for et in original:
            assert catalog.get(et) is not None, f"Original event missing: {et}"

    def test_new_deploy_events_registered(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        for et in [
            "domain.software-development.deploy.triggered",
            "domain.software-development.deploy.succeeded",
            "domain.software-development.deploy.failed",
        ]:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_new_ops_events_registered(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        for et in [
            "domain.software-development.ops.alert_fired",
            "domain.software-development.ops.alert_resolved",
        ]:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_new_maintenance_events_registered(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        for et in [
            "domain.software-development.maintenance.dependency_update",
            "domain.software-development.maintenance.security_patch",
        ]:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_deploy_failed_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        schema = catalog.get("domain.software-development.deploy.failed")
        assert schema is not None
        assert schema.actionable is True

    def test_ops_alert_fired_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        schema = catalog.get("domain.software-development.ops.alert_fired")
        assert schema is not None
        assert schema.actionable is True

    def test_maintenance_security_patch_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_software_development(catalog)
        schema = catalog.get("domain.software-development.maintenance.security_patch")
        assert schema is not None
        assert schema.actionable is True


class TestMarketingSchemas:
    def test_all_marketing_events_registered(self) -> None:
        catalog = EventCatalog()
        register_marketing(catalog)
        expected = [
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
        ]
        for et in expected:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_budget_threshold_hit_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_marketing(catalog)
        schema = catalog.get("domain.marketing.campaign.budget_threshold_hit")
        assert schema is not None
        assert schema.actionable is True

    def test_synthesis_ready_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_marketing(catalog)
        schema = catalog.get("domain.marketing.feed.synthesis_ready")
        assert schema is not None
        assert schema.actionable is True

    def test_all_events_have_marketing_domain(self) -> None:
        catalog = EventCatalog()
        register_marketing(catalog)
        for schema in catalog.list_all():
            assert schema.domain == "marketing", f"Wrong domain on {schema.event_type}"


class TestCreativeProductionSchemas:
    def test_all_creative_production_events_registered(self) -> None:
        catalog = EventCatalog()
        register_creative_production(catalog)
        expected = [
            "domain.creative-production.asset.brief_created",
            "domain.creative-production.asset.draft_submitted",
            "domain.creative-production.asset.review_requested",
            "domain.creative-production.asset.revision_requested",
            "domain.creative-production.asset.approved",
            "domain.creative-production.asset.delivered",
            "domain.creative-production.format.transcode_started",
            "domain.creative-production.format.transcode_completed",
            "domain.creative-production.format.transcode_failed",
        ]
        for et in expected:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_review_requested_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_creative_production(catalog)
        schema = catalog.get("domain.creative-production.asset.review_requested")
        assert schema is not None
        assert schema.actionable is True

    def test_transcode_failed_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_creative_production(catalog)
        schema = catalog.get("domain.creative-production.format.transcode_failed")
        assert schema is not None
        assert schema.actionable is True

    def test_all_events_have_creative_production_domain(self) -> None:
        catalog = EventCatalog()
        register_creative_production(catalog)
        for schema in catalog.list_all():
            assert schema.domain == "creative-production", f"Wrong domain on {schema.event_type}"


class TestCustomerRelationsSchemas:
    def test_all_customer_relations_events_registered(self) -> None:
        catalog = EventCatalog()
        register_customer_relations(catalog)
        expected = [
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
        ]
        for et in expected:
            assert catalog.get(et) is not None, f"Missing: {et}"

    def test_ticket_escalated_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_customer_relations(catalog)
        schema = catalog.get("domain.customer-relations.helpdesk.ticket_escalated")
        assert schema is not None
        assert schema.actionable is True

    def test_escalation_triggered_is_actionable(self) -> None:
        catalog = EventCatalog()
        register_customer_relations(catalog)
        schema = catalog.get("domain.customer-relations.escalation.triggered")
        assert schema is not None
        assert schema.actionable is True

    def test_all_events_have_customer_relations_domain(self) -> None:
        catalog = EventCatalog()
        register_customer_relations(catalog)
        for schema in catalog.list_all():
            assert schema.domain == "customer-relations", f"Wrong domain on {schema.event_type}"


class TestAllDomainsRegistered:
    def test_build_default_catalog_has_all_four_pillar_domains(self) -> None:
        catalog = build_default_catalog()
        domains = {s.domain for s in catalog.list_all()}
        assert "software-development" in domains
        assert "marketing" in domains
        assert "creative-production" in domains
        assert "customer-relations" in domains

    def test_no_duplicate_event_types_across_domains(self) -> None:
        catalog = build_default_catalog()
        seen: set[str] = set()
        for schema in catalog.list_all():
            assert schema.event_type not in seen, f"Duplicate event type: {schema.event_type}"
            seen.add(schema.event_type)

    def test_naming_convention_domain_slug_category_action(self) -> None:
        catalog = build_default_catalog()
        domain_prefixed = [s for s in catalog.list_all() if s.event_type.startswith("domain.")]
        for schema in domain_prefixed:
            parts = schema.event_type.split(".")
            assert len(parts) >= 4, f"Event type too short: {schema.event_type}"
