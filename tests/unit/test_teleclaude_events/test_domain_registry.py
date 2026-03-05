"""Tests for domain_registry: slugify, path resolution, list_enabled."""

from __future__ import annotations

from pathlib import Path

from teleclaude_events.domain_config import DomainConfig, DomainsConfig
from teleclaude_events.domain_registry import DomainRegistry, _slugify_email


class TestSlugifyEmail:
    def test_simple_email(self) -> None:
        assert _slugify_email("alice@example.com") == "alice-example-com"

    def test_email_with_plus(self) -> None:
        assert _slugify_email("alice+tag@example.com") == "alice-tag-example-com"

    def test_uppercase_lowered(self) -> None:
        assert _slugify_email("Alice@Example.COM") == "alice-example-com"

    def test_consecutive_special_chars_collapsed(self) -> None:
        result = _slugify_email("a..b@c--d.com")
        assert "-" in result
        assert ".." not in result

    def test_no_leading_trailing_dash(self) -> None:
        result = _slugify_email("alice@example.com")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_numeric_email(self) -> None:
        assert _slugify_email("user123@host456.org") == "user123-host456-org"


class TestDomainRegistryPaths:
    def _make_registry(self, base: str = "/base", personal_base: str = "/personal") -> DomainRegistry:
        config = DomainsConfig(
            base_path=base,
            personal_base_path=personal_base,
            domains={
                "sales": DomainConfig(name="sales"),
                "custom": DomainConfig(
                    name="custom", cartridge_path="/custom/path/cartridges"
                ),
            },
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        return registry

    def test_cartridge_path_default_branch(self) -> None:
        registry = self._make_registry(base="/base")
        path = registry.cartridge_path_for("sales")
        assert path == Path("/base/domains/sales/cartridges")

    def test_cartridge_path_custom_branch(self) -> None:
        registry = self._make_registry()
        path = registry.cartridge_path_for("custom")
        assert path == Path("/custom/path/cartridges")

    def test_personal_path_uses_slug(self) -> None:
        registry = self._make_registry(personal_base="/personal")
        path = registry.personal_path_for("alice@example.com")
        assert path == Path("/personal/members/alice-example-com/cartridges")

    def test_personal_path_different_emails_different_dirs(self) -> None:
        registry = self._make_registry()
        p1 = registry.personal_path_for("alice@a.com")
        p2 = registry.personal_path_for("bob@b.com")
        assert p1 != p2

    def test_unknown_domain_uses_default_path(self) -> None:
        registry = self._make_registry(base="/base")
        path = registry.cartridge_path_for("unknown")
        assert path == Path("/base/domains/unknown/cartridges")


class TestListEnabled:
    def test_all_enabled_by_default(self) -> None:
        config = DomainsConfig(
            domains={
                "a": DomainConfig(name="a"),
                "b": DomainConfig(name="b"),
            }
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        enabled = registry.list_enabled()
        assert {d.name for d in enabled} == {"a", "b"}

    def test_disabled_domain_excluded(self) -> None:
        config = DomainsConfig(
            domains={
                "active": DomainConfig(name="active", enabled=True),
                "inactive": DomainConfig(name="inactive", enabled=False),
            }
        )
        registry = DomainRegistry()
        registry.load_from_config(config)
        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "active"

    def test_empty_domains_returns_empty(self) -> None:
        config = DomainsConfig(domains={})
        registry = DomainRegistry()
        registry.load_from_config(config)
        assert registry.list_enabled() == []
