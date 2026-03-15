"""Characterization tests for teleclaude.events.startup."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import yaml

from teleclaude.events.domain_config import DomainConfig, DomainsConfig
from teleclaude.events.domain_pipeline import DomainPipelineRunner
from teleclaude.events.startup import build_domain_pipeline_runner


def _write_cartridge(parent: Path, cid: str = "c1") -> None:
    cdir = parent / cid
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "manifest.yaml").write_text(yaml.dump({"id": cid, "description": "test cart"}))
    (cdir / "cartridge.py").write_text(dedent("async def process(event, ctx): return event"))


class TestBuildDomainPipelineRunner:
    def test_returns_domain_pipeline_runner(self) -> None:
        config = DomainsConfig(enabled=False)
        runner = build_domain_pipeline_runner(config)
        assert isinstance(runner, DomainPipelineRunner)

    def test_returns_empty_runner_when_disabled(self) -> None:
        config = DomainsConfig(enabled=False)
        runner = build_domain_pipeline_runner(config)
        assert runner._pipelines == {}

    def test_skips_domain_without_cartridges(self, tmp_path: Path) -> None:
        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"eng": DomainConfig(name="eng")},
        )
        with patch("teleclaude.events.startup.load_global_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(people=[])
            runner = build_domain_pipeline_runner(config)
        # Empty cartridge dir → domain not registered
        assert "eng" not in runner._pipelines

    def test_loads_domain_with_cartridges(self, tmp_path: Path) -> None:
        from teleclaude.events.domain_config import DomainConfig

        cart_path = tmp_path / "domains" / "eng" / "cartridges"
        cart_path.mkdir(parents=True)
        _write_cartridge(cart_path, "c1")

        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"eng": DomainConfig(name="eng")},
        )
        with patch("teleclaude.events.startup.load_global_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(people=[])
            runner = build_domain_pipeline_runner(config)
        assert "eng" in runner._pipelines

    def test_skips_domain_on_cartridge_error(self, tmp_path: Path) -> None:
        from teleclaude.events.domain_config import DomainConfig

        cart_path = tmp_path / "domains" / "eng" / "cartridges"
        cart_path.mkdir(parents=True)
        # Cartridge with invalid module — will fail to load
        broken = cart_path / "broken"
        broken.mkdir()
        (broken / "manifest.yaml").write_text(yaml.dump({"id": "broken", "description": "d"}))
        # No cartridge.py — load will fail
        config = DomainsConfig(
            base_path=str(tmp_path),
            domains={"eng": DomainConfig(name="eng")},
        )
        with patch("teleclaude.events.startup.load_global_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(people=[])
            # Should not raise — broken domain is skipped
            runner = build_domain_pipeline_runner(config)
        # Broken cartridge is skipped (warning only); domain may still not be registered
        assert isinstance(runner, DomainPipelineRunner)

    def test_loads_personal_pipeline_for_people(self, tmp_path: Path) -> None:
        personal_base = tmp_path / "personal"
        personal_base.mkdir()

        config = DomainsConfig(
            base_path=str(tmp_path),
            personal_base_path=str(personal_base),
        )
        person = MagicMock()
        person.email = "user@example.com"

        with patch("teleclaude.events.startup.load_global_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(people=[person])
            runner = build_domain_pipeline_runner(config)
        # Personal path has no cartridges → not registered, but no crash
        assert isinstance(runner, DomainPipelineRunner)

    def test_tolerates_global_config_failure(self) -> None:
        config = DomainsConfig(enabled=True, domains={})
        with patch(
            "teleclaude.events.startup.load_global_config",
            side_effect=RuntimeError("config error"),
        ):
            runner = build_domain_pipeline_runner(config)
        assert isinstance(runner, DomainPipelineRunner)
