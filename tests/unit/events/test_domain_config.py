"""Characterization tests for teleclaude.events.domain_config."""

from __future__ import annotations

from teleclaude.events.domain_config import (
    AutonomyLevel,
    AutonomyMatrix,
    DomainConfig,
    DomainsConfig,
)


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


class TestDomainConfig:
    def test_extra_fields_allowed(self) -> None:
        d = DomainConfig.model_validate({"name": "eng", "extra_setting": True})
        assert d.model_extra is not None
        assert d.model_extra.get("extra_setting") is True


class TestDomainsConfig:
    def test_extra_fields_allowed(self) -> None:
        c = DomainsConfig.model_validate({"unknown_field": "x"})
        assert c.model_extra is not None
