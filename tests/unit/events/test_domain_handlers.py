"""Tests for the static domain handler registry."""

from __future__ import annotations

from teleclaude.events.domain_handlers import DomainDependencyError, build_handler_levels, handler_ids_for_domain


def test_unknown_domain_has_no_handlers() -> None:
    assert handler_ids_for_domain("unknown-domain") == ()
    assert build_handler_levels("unknown-domain") == []


def test_marketing_handlers_are_registered() -> None:
    assert handler_ids_for_domain("marketing") == (
        "content-pipeline",
        "campaign-budget-monitor",
        "feed-monitor",
    )


def test_creative_production_dependency_order_is_respected() -> None:
    levels = build_handler_levels("creative-production")
    assert [handler.handler_id for handler in levels[0]] == ["asset-lifecycle"]
    assert [handler.handler_id for handler in levels[1]] == ["review-gatekeeper"]


def test_customer_relations_dependency_order_is_respected() -> None:
    levels = build_handler_levels("customer-relations")
    assert "helpdesk-triage" in [handler.handler_id for handler in levels[0]]
    assert [handler.handler_id for handler in levels[1]] == ["escalation-handler"]


def test_domain_dependency_error_is_exception() -> None:
    err = DomainDependencyError("bad dependency")
    assert isinstance(err, Exception)
