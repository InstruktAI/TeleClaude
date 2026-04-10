"""Domain pipeline startup — build DomainPipelineRunner from static registry."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.events.domain_config import DomainsConfig
from teleclaude.events.domain_handlers import DomainHandlerError, build_handler_levels
from teleclaude.events.domain_pipeline import DomainPipeline, DomainPipelineRunner

logger = get_logger(__name__)


def _register_domain_pipelines(config: DomainsConfig, runner: DomainPipelineRunner) -> None:
    """Register all enabled domain pipelines from the static handler registry."""
    for domain_name, domain_cfg in config.domains.items():
        if not domain_cfg.enabled:
            continue
        try:
            normalized_cfg = (
                domain_cfg if domain_cfg.name == domain_name else domain_cfg.model_copy(update={"name": domain_name})
            )
            levels = build_handler_levels(domain_name)
            if not levels:
                logger.debug("No domain handlers registered for domain '%s'", domain_name)
                continue

            pipeline = DomainPipeline(domain=normalized_cfg, levels=levels)
            runner.register_domain_pipeline(domain_name, pipeline)
            logger.info(
                "Loaded domain pipeline '%s': %d handlers across %d levels",
                domain_name,
                sum(len(level) for level in levels),
                len(levels),
            )
        except DomainHandlerError as exc:
            logger.error(
                "Failed to load domain pipeline '%s': %s — domain pipeline disabled",
                domain_name,
                exc,
                exc_info=True,
            )


def build_domain_pipeline_runner(config: DomainsConfig) -> DomainPipelineRunner:
    """Build a DomainPipelineRunner from config.

    On startup error (e.g., CartridgeCycleError): logs the error and skips the
    affected domain — domain failures do not crash the runner.
    """
    runner = DomainPipelineRunner()

    if not config.enabled:
        logger.info("Domain pipeline disabled in config")
        return runner

    _register_domain_pipelines(config, runner)

    return runner
