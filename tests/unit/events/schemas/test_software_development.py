"""Characterization tests for teleclaude.events.schemas.software_development."""

from __future__ import annotations

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventLevel
from teleclaude.events.schemas.software_development import register_software_development

_EXPECTED_TYPES = {
    # Planning
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_dumped",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.dependency_resolved",
    "domain.software-development.planning.dor_assessed",
    # Build
    "domain.software-development.build.completed",
    # Review
    "domain.software-development.review.verdict_ready",
    "domain.software-development.review.needs_decision",
    "domain.software-development.review.approved",
    # Deploy
    "domain.software-development.deploy.triggered",
    "domain.software-development.deploy.succeeded",
    "domain.software-development.deploy.failed",
    # Ops
    "domain.software-development.ops.alert_fired",
    "domain.software-development.ops.alert_resolved",
    # Maintenance
    "domain.software-development.maintenance.dependency_update",
    "domain.software-development.maintenance.security_patch",
    # Prepare
    "domain.software-development.prepare.input_refined",
    "domain.software-development.prepare.discovery_started",
    "domain.software-development.prepare.requirements_drafted",
    "domain.software-development.prepare.requirements_approved",
    "domain.software-development.prepare.plan_drafted",
    "domain.software-development.prepare.plan_approved",
    "domain.software-development.prepare.grounding_invalidated",
    "domain.software-development.prepare.regrounded",
    "domain.software-development.prepare.completed",
    "domain.software-development.prepare.blocked",
    "domain.software-development.prepare.phase_skipped",
    "domain.software-development.prepare.input_consumed",
    "domain.software-development.prepare.artifact_produced",
    "domain.software-development.prepare.artifact_invalidated",
    "domain.software-development.prepare.finding_recorded",
    "domain.software-development.prepare.finding_resolved",
    "domain.software-development.prepare.review_scoped",
    "domain.software-development.prepare.split_inherited",
    # Integration
    "domain.software-development.branch.pushed",
    "domain.software-development.deployment.started",
    "domain.software-development.deployment.completed",
    "domain.software-development.deployment.failed",
}


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_software_development(catalog)
    return catalog


def test_register_software_development_registers_all_expected_types() -> None:
    types = {s.event_type for s in _catalog().list_all()}
    assert types == _EXPECTED_TYPES


def test_all_events_have_software_development_domain() -> None:
    for schema in _catalog().list_all():
        assert schema.domain == "software-development"


def test_dor_assessed_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.planning.dor_assessed")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.WORKFLOW


def test_dor_assessed_creates_and_updates() -> None:
    schema = _catalog().get("domain.software-development.planning.dor_assessed")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.updates is True


def test_review_needs_decision_is_actionable_and_business_level() -> None:
    schema = _catalog().get("domain.software-development.review.needs_decision")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_deploy_failed_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.deploy.failed")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_ops_alert_fired_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.ops.alert_fired")
    assert schema is not None
    assert schema.actionable is True


def test_maintenance_security_patch_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.maintenance.security_patch")
    assert schema is not None
    assert schema.actionable is True
    assert schema.default_level == EventLevel.BUSINESS


def test_prepare_blocked_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.prepare.blocked")
    assert schema is not None
    assert schema.actionable is True


def test_prepare_completed_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.software-development.prepare.completed")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True


def test_deployment_completed_resolves_lifecycle() -> None:
    schema = _catalog().get("domain.software-development.deployment.completed")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True


def test_deployment_failed_is_actionable() -> None:
    schema = _catalog().get("domain.software-development.deployment.failed")
    assert schema is not None
    assert schema.actionable is True
