"""Characterization tests for teleclaude.events.domain_config."""

from __future__ import annotations

from teleclaude.events.domain_config import (
    AutonomyLevel,
    AutonomyMatrix,
    DomainConfig,
    DomainGuardianConfig,
    DomainsConfig,
)


class TestAutonomyLevel:
    def test_manual_value(self) -> None:
        assert AutonomyLevel.MANUAL.value == "manual"

    def test_notify_value(self) -> None:
        assert AutonomyLevel.NOTIFY.value == "notify"

    def test_auto_notify_value(self) -> None:
        assert AutonomyLevel.AUTO_NOTIFY.value == "auto_notify"

    def test_autonomous_value(self) -> None:
        assert AutonomyLevel.AUTONOMOUS.value == "autonomous"


class TestAutonomyMatrix:
    def test_global_default_is_notify(self) -> None:
        m = AutonomyMatrix()
        assert m.global_default == AutonomyLevel.NOTIFY

    def test_resolve_returns_global_default_when_no_overrides(self) -> None:
        m = AutonomyMatrix(global_default=AutonomyLevel.AUTONOMOUS)
        result = m.resolve("dom", "cart", "evt")
        assert result == AutonomyLevel.AUTONOMOUS

    def test_resolve_domain_override(self) -> None:
        m = AutonomyMatrix(by_domain={"eng": AutonomyLevel.MANUAL})
        result = m.resolve("eng", "cart", "evt")
        assert result == AutonomyLevel.MANUAL

    def test_resolve_cartridge_overrides_domain(self) -> None:
        m = AutonomyMatrix(
            by_domain={"eng": AutonomyLevel.MANUAL},
            by_cartridge={"eng/cart": AutonomyLevel.AUTO_NOTIFY},
        )
        result = m.resolve("eng", "cart", "evt")
        assert result == AutonomyLevel.AUTO_NOTIFY

    def test_resolve_event_type_overrides_cartridge(self) -> None:
        m = AutonomyMatrix(
            by_domain={"eng": AutonomyLevel.MANUAL},
            by_cartridge={"eng/cart": AutonomyLevel.AUTO_NOTIFY},
            by_event_type={"eng/evt": AutonomyLevel.AUTONOMOUS},
        )
        result = m.resolve("eng", "cart", "evt")
        assert result == AutonomyLevel.AUTONOMOUS

    def test_resolve_event_key_format(self) -> None:
        m = AutonomyMatrix(by_event_type={"dom/specific.event": AutonomyLevel.NOTIFY})
        result = m.resolve("dom", "any-cart", "specific.event")
        assert result == AutonomyLevel.NOTIFY

    def test_resolve_cartridge_key_format(self) -> None:
        m = AutonomyMatrix(by_cartridge={"dom/specific-cart": AutonomyLevel.AUTONOMOUS})
        result = m.resolve("dom", "specific-cart", "any.event")
        assert result == AutonomyLevel.AUTONOMOUS


class TestDomainGuardianConfig:
    def test_agent_default(self) -> None:
        g = DomainGuardianConfig()
        assert g.agent == "claude"

    def test_mode_default(self) -> None:
        g = DomainGuardianConfig()
        assert g.mode == "med"

    def test_enabled_default_true(self) -> None:
        g = DomainGuardianConfig()
        assert g.enabled is True

    def test_evaluation_prompt_default_none(self) -> None:
        g = DomainGuardianConfig()
        assert g.evaluation_prompt is None


class TestDomainConfig:
    def test_enabled_default_true(self) -> None:
        d = DomainConfig(name="eng")
        assert d.enabled is True

    def test_cartridge_path_default_none(self) -> None:
        d = DomainConfig(name="eng")
        assert d.cartridge_path is None

    def test_has_guardian(self) -> None:
        d = DomainConfig(name="eng")
        assert isinstance(d.guardian, DomainGuardianConfig)

    def test_has_autonomy_matrix(self) -> None:
        d = DomainConfig(name="eng")
        assert isinstance(d.autonomy, AutonomyMatrix)

    def test_extra_fields_allowed(self) -> None:
        d = DomainConfig.model_validate({"name": "eng", "extra_setting": True})
        assert d.model_extra is not None
        assert d.model_extra.get("extra_setting") is True


class TestDomainsConfig:
    def test_enabled_default_true(self) -> None:
        c = DomainsConfig()
        assert c.enabled is True

    def test_base_path_default(self) -> None:
        c = DomainsConfig()
        assert c.base_path == "~/.teleclaude/company"

    def test_personal_base_path_default(self) -> None:
        c = DomainsConfig()
        assert c.personal_base_path == "~/.teleclaude/personal"

    def test_domains_default_empty(self) -> None:
        c = DomainsConfig()
        assert c.domains == {}

    def test_extra_fields_allowed(self) -> None:
        c = DomainsConfig.model_validate({"unknown_field": "x"})
        assert c.model_extra is not None
