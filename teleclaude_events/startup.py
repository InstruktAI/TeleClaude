"""Domain pipeline startup — build DomainPipelineRunner from config."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config
from teleclaude_events.cartridge_loader import discover_cartridges, resolve_dag, validate_pipeline
from teleclaude_events.cartridge_manifest import CartridgeError
from teleclaude_events.domain_config import DomainsConfig
from teleclaude_events.domain_pipeline import DomainPipeline, DomainPipelineRunner
from teleclaude_events.domain_registry import DomainRegistry
from teleclaude_events.personal_pipeline import load_personal_pipeline

logger = get_logger(__name__)


def build_domain_pipeline_runner(config: DomainsConfig) -> DomainPipelineRunner:
    """Build a DomainPipelineRunner from config.

    On startup error (e.g., CartridgeCycleError): logs the error and skips the
    affected domain — domain failures do not crash the runner.
    """
    runner = DomainPipelineRunner()

    if not config.enabled:
        logger.info("Domain pipeline disabled in config")
        return runner

    registry = DomainRegistry()
    registry.load_from_config(config)

    for domain_cfg in registry.list_enabled():
        domain_name = domain_cfg.name
        cartridge_path = registry.cartridge_path_for(domain_name)

        try:
            cartridges = discover_cartridges(cartridge_path)
            if not cartridges:
                logger.debug("No cartridges found for domain '%s' at %s", domain_name, cartridge_path)
                continue

            levels = resolve_dag(cartridges)
            validate_pipeline(levels, domain_name)
            pipeline = DomainPipeline(domain=domain_cfg, levels=levels)
            runner.register_domain_pipeline(domain_name, pipeline)
            logger.info(
                "Loaded domain pipeline '%s': %d cartridges across %d levels",
                domain_name,
                len(cartridges),
                len(levels),
            )
        except CartridgeError as e:
            logger.error(
                "Failed to load domain pipeline '%s': %s — domain pipeline disabled",
                domain_name,
                e,
                exc_info=True,
            )

    # Build personal pipelines for all configured members
    try:
        global_config = load_global_config()
        people = global_config.people
        for person in people:
            member_id = person.email
            if not member_id:
                continue
            personal_path = registry.personal_path_for(member_id)
            try:
                personal_pipeline = load_personal_pipeline(member_id, personal_path)
                if personal_pipeline.cartridges:
                    runner.register_personal_pipeline(member_id, personal_pipeline)
                    logger.info(
                        "Loaded personal pipeline for '%s': %d cartridges",
                        member_id,
                        len(personal_pipeline.cartridges),
                    )
            except Exception as e:
                logger.error("Failed to load personal pipeline for '%s': %s", member_id, e, exc_info=True)
    except Exception as e:
        logger.warning("Could not load global config for personal pipelines: %s", e, exc_info=True)

    return runner
