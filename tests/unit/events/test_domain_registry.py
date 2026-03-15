"""Characterization tests for teleclaude.events.domain_registry."""

from __future__ import annotations

from pathlib import Path

from teleclaude.events.domain_config import DomainConfig, DomainsConfig
from teleclaude.events.domain_registry import DomainRegistry, _slugify_email


class TestSlugifyEmail:
    def test_simple_email(self) -> None:
        assert _slugify_email("user@example.com") == "user-example-com"

    def test_uppercase_lowercased(self) -> None:
        assert _slugify_email("User@Example.COM") == "user-example-com"

    def test_special_chars_replaced_with_dash(self) -> None:
        result = _slugify_email("first.last+tag@sub.domain.org")
        # letters/digits only separated by dashes, no consecutive dashes required
        assert all(c.isalnum() or c == "-" for c in result)

    def test_no_leading_or_trailing_dash(self) -> None:
        result = _slugify_email("user@example.com")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestDomainRegistry:
    def _registry_with_domains(self) -> DomainRegistry:
        config = DomainsConfig(
            domains={
                "eng": DomainConfig(name="eng", enabled=True),
                "marketing": DomainConfig(name="marketing", enabled=False),
            }
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        return registry

    def test_get_known_domain(self) -> None:
        registry = self._registry_with_domains()
        domain = registry.get("eng")
        assert domain is not None
        assert domain.name == "eng"

    def test_get_unknown_domain_returns_none(self) -> None:
        registry = self._registry_with_domains()
        assert registry.get("unknown") is None

    def test_list_enabled_excludes_disabled(self) -> None:
        registry = self._registry_with_domains()
        names = {d.name for d in registry.list_enabled()}
        assert "eng" in names
        assert "marketing" not in names

    def test_load_from_config_sets_name_from_key(self) -> None:
        config = DomainsConfig(
            domains={
                "fixed-name": DomainConfig(name="wrong-name", enabled=True),
            }
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        domain = registry.get("fixed-name")
        assert domain is not None
        assert domain.name == "fixed-name"

    def test_cartridge_path_uses_custom_if_set(self) -> None:
        config = DomainsConfig(
            domains={
                "eng": DomainConfig(name="eng", cartridge_path="/custom/path"),
            }
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        path = registry.cartridge_path_for("eng")
        assert path == Path("/custom/path")

    def test_cartridge_path_default_uses_base_path(self) -> None:
        config = DomainsConfig(
            base_path="/base",
            domains={"eng": DomainConfig(name="eng")},
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        path = registry.cartridge_path_for("eng")
        assert path == Path("/base/domains/eng/cartridges")

    def test_cartridge_path_for_unknown_domain_uses_default(self) -> None:
        config = DomainsConfig(base_path="/base")
        registry = DomainRegistry()
        registry.load_from_config(config)
        path = registry.cartridge_path_for("unknown-domain")
        assert path == Path("/base/domains/unknown-domain/cartridges")

    def test_personal_path_for_uses_slugified_email(self) -> None:
        config = DomainsConfig(personal_base_path="/personal")
        registry = DomainRegistry()
        registry.load_from_config(config)
        path = registry.personal_path_for("user@example.com")
        slug = _slugify_email("user@example.com")
        assert path == Path(f"/personal/members/{slug}/cartridges")

    def test_empty_registry_list_enabled_returns_empty(self) -> None:
        registry = DomainRegistry()
        assert registry.list_enabled() == []
