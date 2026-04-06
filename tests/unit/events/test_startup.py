"""Characterization tests for teleclaude.events.startup."""

from __future__ import annotations

from teleclaude.events.domain_config import DomainConfig, DomainsConfig
from teleclaude.events.domain_pipeline import DomainPipelineRunner
from teleclaude.events.startup import build_domain_pipeline_runner


class TestBuildDomainPipelineRunner:
    def test_returns_domain_pipeline_runner(self) -> None:
        config = DomainsConfig(enabled=False)
        runner = build_domain_pipeline_runner(config)
        assert isinstance(runner, DomainPipelineRunner)

    def test_returns_empty_runner_when_disabled(self) -> None:
        config = DomainsConfig(enabled=False)
        runner = build_domain_pipeline_runner(config)
        assert runner._pipelines == {}

    def test_skips_domain_without_registered_handlers(self) -> None:
        config = DomainsConfig(domains={"eng": DomainConfig(name="eng")})
        runner = build_domain_pipeline_runner(config)
        assert "eng" not in runner._pipelines

    def test_loads_domain_with_registered_handlers(self) -> None:
        config = DomainsConfig(domains={"marketing": DomainConfig(name="marketing")})
        runner = build_domain_pipeline_runner(config)
        assert "marketing" in runner._pipelines
