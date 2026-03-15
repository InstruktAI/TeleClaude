"""Characterization tests for teleclaude.events.domain_seeds."""

from __future__ import annotations

from typing import Any, cast

from teleclaude.events.domain_seeds import DEFAULT_EVENT_DOMAINS


def _domains() -> dict[str, Any]:  # guard: loose-dict-func - DEFAULT_EVENT_DOMAINS is JsonDict (untyped runtime data)
    return cast(dict[str, Any], DEFAULT_EVENT_DOMAINS["domains"])


def _d(cfg: Any) -> dict[str, Any]:  # guard: loose-dict-func - domain config values are JsonValue (untyped)
    return cast(dict[str, Any], cfg)


def test_domains_key_exists() -> None:
    assert "domains" in DEFAULT_EVENT_DOMAINS


def test_expected_domains_present() -> None:
    domains = _domains()
    expected = {"software-development", "marketing", "creative-production", "customer-relations"}
    assert set(domains.keys()) == expected


def test_each_domain_has_enabled_true() -> None:
    for name, cfg in _domains().items():
        assert _d(cfg)["enabled"] is True, f"{name} not enabled"


def test_each_domain_has_guardian_config() -> None:
    for name, cfg in _domains().items():
        d = _d(cfg)
        assert "guardian" in d, f"{name} missing guardian"
        assert _d(d["guardian"])["enabled"] is True


def test_each_domain_guardian_has_agent_claude() -> None:
    for cfg in _domains().values():
        assert _d(_d(cfg)["guardian"])["agent"] == "claude"


def test_each_domain_has_autonomy_config() -> None:
    for name, cfg in _domains().items():
        d = _d(cfg)
        assert "autonomy" in d, f"{name} missing autonomy"
        assert "by_cartridge" in _d(d["autonomy"])


def test_each_domain_name_matches_key() -> None:
    for key, cfg in _domains().items():
        assert _d(cfg)["name"] == key, f"Domain name mismatch for key {key}"


def test_software_development_cartridges() -> None:
    cartridges = _d(_d(_domains()["software-development"])["autonomy"])["by_cartridge"]
    assert "software-development/todo-lifecycle" in cartridges
    assert "software-development/build-notifier" in cartridges
    assert "software-development/deploy-tracker" in cartridges


def test_customer_relations_has_evaluation_prompt() -> None:
    guardian = _d(_d(_domains()["customer-relations"])["guardian"])
    assert "evaluation_prompt" in guardian
    assert guardian["evaluation_prompt"] is not None
