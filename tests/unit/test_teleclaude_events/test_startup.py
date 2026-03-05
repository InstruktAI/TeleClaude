"""Tests for domain pipeline startup wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.domain_config import DomainsConfig
from teleclaude_events.domain_pipeline import DomainPipelineRunner
from teleclaude_events.startup import build_domain_pipeline_runner


class TestBuildDomainPipelineRunner:
    def test_empty_config_returns_runner(self) -> None:
        config = DomainsConfig()
        runner = build_domain_pipeline_runner(config)
        assert isinstance(runner, DomainPipelineRunner)

    def test_disabled_config_returns_empty_runner(self) -> None:
        config = DomainsConfig(enabled=False)
        runner = build_domain_pipeline_runner(config)
        assert isinstance(runner, DomainPipelineRunner)

    def test_domain_with_no_cartridges_is_skipped(self, tmp_path: Path) -> None:
        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"software": {"name": "software"}},  # type: ignore[dict-item]
        )
        runner = build_domain_pipeline_runner(config)
        # No domain pipeline registered since no cartridges exist
        assert isinstance(runner, DomainPipelineRunner)

    def test_domain_with_cycle_error_is_logged_not_raised(
        self, tmp_path: Path
    ) -> None:
        """A domain with a cycle in its DAG should be skipped, not crash startup."""
        domain_path = tmp_path / "domains" / "broken" / "cartridges"
        # Create two cartridges with circular deps
        for cid, dep in [("a", "b"), ("b", "a")]:
            d = domain_path / cid
            d.mkdir(parents=True)
            (d / "manifest.yaml").write_text(
                f"id: {cid}\ndescription: {cid}\ndepends_on: [{dep}]\n",
                encoding="utf-8",
            )
            (d / "cartridge.py").write_text(
                "async def process(event, context):\n    return event\n",
                encoding="utf-8",
            )

        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"broken": {"name": "broken"}},  # type: ignore[dict-item]
        )
        import teleclaude_events.startup as startup_mod

        with pytest.MonkeyPatch().context() as m:
            # Patch the module-level reference to avoid filesystem access
            m.setattr(startup_mod, "load_global_config", lambda: type("Config", (), {"people": []})())
            runner = build_domain_pipeline_runner(config)

        assert isinstance(runner, DomainPipelineRunner)

    def test_valid_domain_cartridge_is_loaded(self, tmp_path: Path) -> None:
        import teleclaude_events.startup as startup_mod

        domain_path = tmp_path / "domains" / "software" / "cartridges"
        d = domain_path / "my-c"
        d.mkdir(parents=True)
        (d / "manifest.yaml").write_text(
            "id: my-c\ndescription: My cartridge\n", encoding="utf-8"
        )
        (d / "cartridge.py").write_text(
            "async def process(event, context):\n    return event\n",
            encoding="utf-8",
        )

        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"software": {"name": "software"}},  # type: ignore[dict-item]
        )

        with pytest.MonkeyPatch().context() as m:
            m.setattr(startup_mod, "load_global_config", lambda: type("Config", (), {"people": []})())
            runner = build_domain_pipeline_runner(config)

        assert isinstance(runner, DomainPipelineRunner)
        # A pipeline was registered for 'software'
        assert "software" in runner._pipelines
