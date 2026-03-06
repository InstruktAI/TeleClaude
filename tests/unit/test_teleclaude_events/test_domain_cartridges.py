"""Tests for domain pillar cartridge manifests and config seeding."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude_events.cartridge_manifest import CartridgeManifest
from teleclaude_events.domain_config import DomainsConfig
from teleclaude_events.domain_seeds import DEFAULT_EVENT_DOMAINS

# Resolve the starter cartridge directory from the user home
_DOMAINS_BASE = Path("~/.teleclaude/company/domains").expanduser()


def _manifest_path(domain: str, cartridge_id: str) -> Path:
    return _DOMAINS_BASE / domain / "cartridges" / cartridge_id / "manifest.yaml"


class TestDefaultEventDomains:
    def test_has_all_four_pillars(self) -> None:
        domains = DEFAULT_EVENT_DOMAINS["domains"]
        assert "software-development" in domains
        assert "marketing" in domains
        assert "creative-production" in domains
        assert "customer-relations" in domains

    def test_customer_relations_has_strict_trust_threshold(self) -> None:
        cr = DEFAULT_EVENT_DOMAINS["domains"]["customer-relations"]
        assert cr["guardian"]["trust_threshold"] == "strict"

    def test_all_domains_have_guardian(self) -> None:
        for name, domain in DEFAULT_EVENT_DOMAINS["domains"].items():
            assert "guardian" in domain, f"Missing guardian for {name}"
            assert domain["guardian"]["agent"] == "claude"

    def test_all_domains_are_enabled(self) -> None:
        for name, domain in DEFAULT_EVENT_DOMAINS["domains"].items():
            assert domain["enabled"] is True, f"Domain {name} is not enabled"

    def test_domains_config_validates(self) -> None:
        config = DomainsConfig.model_validate(DEFAULT_EVENT_DOMAINS)
        assert len(config.domains) == 4


class TestSoftwareDevelopmentCartridgeManifests:
    @pytest.mark.skipif(
        not _manifest_path("software-development", "todo-lifecycle").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_todo_lifecycle_manifest_valid(self) -> None:
        path = _manifest_path("software-development", "todo-lifecycle")
        raw = yaml.safe_load(path.read_text())
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "todo-lifecycle"
        assert "software-development" in manifest.domain_affinity
        assert manifest.depends_on == []
        et = raw.get("event_types", [])
        assert "domain.software-development.planning.todo_created" in et
        assert "domain.software-development.planning.dor_assessed" in et

    @pytest.mark.skipif(
        not _manifest_path("software-development", "build-notifier").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_build_notifier_manifest_valid(self) -> None:
        path = _manifest_path("software-development", "build-notifier")
        raw = yaml.safe_load(path.read_text())
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "build-notifier"
        et = raw.get("event_types", [])
        assert "domain.software-development.build.completed" in et

    @pytest.mark.skipif(
        not _manifest_path("software-development", "deploy-tracker").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_deploy_tracker_manifest_valid(self) -> None:
        path = _manifest_path("software-development", "deploy-tracker")
        raw = yaml.safe_load(path.read_text())
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "deploy-tracker"
        et = raw.get("event_types", [])
        assert "domain.software-development.deploy.triggered" in et
        assert "domain.software-development.deploy.failed" in et


class TestMarketingCartridgeManifests:
    @pytest.mark.skipif(
        not _manifest_path("marketing", "feed-monitor").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_feed_monitor_depends_on_signal_pipeline(self) -> None:
        path = _manifest_path("marketing", "feed-monitor")
        raw = yaml.safe_load(path.read_text())
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "feed-monitor"
        assert "signal-ingest" in manifest.depends_on
        assert "signal-cluster" in manifest.depends_on
        assert "signal-synthesize" in manifest.depends_on

    @pytest.mark.skipif(
        not _manifest_path("marketing", "content-pipeline").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_content_pipeline_manifest_valid(self) -> None:
        path = _manifest_path("marketing", "content-pipeline")
        raw = yaml.safe_load(path.read_text())
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "content-pipeline"
        assert "marketing" in manifest.domain_affinity


class TestCustomerRelationsCartridgeManifests:
    @pytest.mark.skipif(
        not _manifest_path("customer-relations", "helpdesk-triage").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_helpdesk_triage_has_strict_trust(self) -> None:
        path = _manifest_path("customer-relations", "helpdesk-triage")
        raw = yaml.safe_load(path.read_text())
        assert raw.get("trust_required") == "strict"

    @pytest.mark.skipif(
        not _manifest_path("customer-relations", "escalation-handler").exists(),
        reason="Starter cartridges not installed (run telec init)",
    )
    def test_escalation_handler_has_strict_trust(self) -> None:
        path = _manifest_path("customer-relations", "escalation-handler")
        raw = yaml.safe_load(path.read_text())
        assert raw.get("trust_required") == "strict"


class TestConfigSeeding:
    def test_seed_event_domains_is_idempotent(self, tmp_path: Path) -> None:
        """Calling seed_event_domains twice produces the same result."""
        from teleclaude.project_setup.domain_seeds import seed_event_domains

        # Create a minimal global config file
        config_file = tmp_path / "teleclaude.yml"
        config_file.write_text("people: []\n", encoding="utf-8")

        import teleclaude.project_setup.domain_seeds as seeds_mod

        original_path = seeds_mod._GLOBAL_CONFIG_PATH
        seeds_mod._GLOBAL_CONFIG_PATH = config_file  # type: ignore[assignment]
        try:
            seed_event_domains(tmp_path)
            content_first = config_file.read_text()
            seed_event_domains(tmp_path)
            content_second = config_file.read_text()
        finally:
            seeds_mod._GLOBAL_CONFIG_PATH = original_path  # type: ignore[assignment]

        assert content_first == content_second

    def test_seed_event_domains_populates_all_four_pillars(self, tmp_path: Path) -> None:
        """Seeding adds all four pillar domains to an empty config."""
        from teleclaude.project_setup.domain_seeds import seed_event_domains

        config_file = tmp_path / "teleclaude.yml"
        config_file.write_text("people: []\n", encoding="utf-8")

        import teleclaude.project_setup.domain_seeds as seeds_mod

        original_path = seeds_mod._GLOBAL_CONFIG_PATH
        seeds_mod._GLOBAL_CONFIG_PATH = config_file  # type: ignore[assignment]
        try:
            seed_event_domains(tmp_path)
            raw = yaml.safe_load(config_file.read_text())
        finally:
            seeds_mod._GLOBAL_CONFIG_PATH = original_path  # type: ignore[assignment]

        domains = raw["event_domains"]["domains"]
        assert "software-development" in domains
        assert "marketing" in domains
        assert "creative-production" in domains
        assert "customer-relations" in domains

    def test_seed_event_domains_skips_when_populated(self, tmp_path: Path) -> None:
        """Seeding is a no-op when event_domains.domains already has entries."""
        from teleclaude.project_setup.domain_seeds import seed_event_domains

        config_file = tmp_path / "teleclaude.yml"
        config_file.write_text(
            "people: []\nevent_domains:\n  domains:\n    my-domain:\n      name: my-domain\n",
            encoding="utf-8",
        )
        original_content = config_file.read_text()

        import teleclaude.project_setup.domain_seeds as seeds_mod

        original_path = seeds_mod._GLOBAL_CONFIG_PATH
        seeds_mod._GLOBAL_CONFIG_PATH = config_file  # type: ignore[assignment]
        try:
            seed_event_domains(tmp_path)
            content_after = config_file.read_text()
        finally:
            seeds_mod._GLOBAL_CONFIG_PATH = original_path  # type: ignore[assignment]

        assert content_after == original_content

    def test_seed_event_domains_customer_relations_strict(self, tmp_path: Path) -> None:
        """Customer-relations guardian has trust_threshold: strict after seeding."""
        from teleclaude.project_setup.domain_seeds import seed_event_domains

        config_file = tmp_path / "teleclaude.yml"
        config_file.write_text("people: []\n", encoding="utf-8")

        import teleclaude.project_setup.domain_seeds as seeds_mod

        original_path = seeds_mod._GLOBAL_CONFIG_PATH
        seeds_mod._GLOBAL_CONFIG_PATH = config_file  # type: ignore[assignment]
        try:
            seed_event_domains(tmp_path)
            raw = yaml.safe_load(config_file.read_text())
        finally:
            seeds_mod._GLOBAL_CONFIG_PATH = original_path  # type: ignore[assignment]

        cr_guardian = raw["event_domains"]["domains"]["customer-relations"]["guardian"]
        assert cr_guardian["trust_threshold"] == "strict"
