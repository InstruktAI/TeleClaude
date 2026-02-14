"""Config loading for webhook service hooks section."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target

if TYPE_CHECKING:
    from teleclaude.hooks.inbound import InboundEndpointRegistry
    from teleclaude.hooks.registry import ContractRegistry  # type: ignore[import-not-found]  # Track B dependency

logger = get_logger(__name__)


def parse_criterion(data: dict[str, Any]) -> PropertyCriterion:  # guard: loose-dict - Config YAML is unstructured
    """Parse a criterion dict from config into PropertyCriterion."""
    return PropertyCriterion(
        match=data.get("match"),
        pattern=data.get("pattern"),
        required=data.get("required", True),
    )


async def load_hooks_config(
    hooks_config: dict[str, Any],  # guard: loose-dict - Config YAML is unstructured
    contract_registry: ContractRegistry,
    inbound_registry: InboundEndpointRegistry | None = None,
) -> None:
    """Load hooks configuration and register contracts + inbound endpoints.

    Args:
        hooks_config: The 'hooks' section from teleclaude.yml
        contract_registry: Registry to register contracts into
        inbound_registry: Optional inbound endpoint registry
    """
    # Load subscriptions (contracts)
    subscriptions = hooks_config.get("subscriptions", [])
    for sub in subscriptions:
        try:
            contract_data = sub.get("contract", {})
            target_data = sub.get("target", {})

            # Extract source and type criteria from contract
            source_criterion = None
            type_criterion = None
            properties: dict[str, PropertyCriterion] = {}

            for key, value in contract_data.items():
                if not isinstance(value, dict):
                    continue
                criterion = parse_criterion(value)
                if key == "source":
                    source_criterion = criterion
                elif key == "type":
                    type_criterion = criterion
                else:
                    properties[key] = criterion

            target = Target(
                handler=target_data.get("handler"),
                url=target_data.get("url"),
                secret=target_data.get("secret"),
            )

            contract = Contract(
                id=sub["id"],
                target=target,
                source_criterion=source_criterion,
                type_criterion=type_criterion,
                properties=properties,
                source="config",
            )
            await contract_registry.register(contract)
            logger.info("Loaded config contract: %s", contract.id)

        except Exception as exc:
            logger.error("Failed to load subscription %s: %s", sub.get("id", "?"), exc)

    # Load inbound endpoints
    if inbound_registry:
        inbound = hooks_config.get("inbound", {})
        for source_name, source_config in inbound.items():
            try:
                path = source_config.get("path", f"/hooks/{source_name}")
                normalizer_key = source_config.get("normalizer", source_name)
                verify_config = {}
                if "verify_token" in source_config:
                    verify_config["verify_token"] = source_config["verify_token"]
                if "secret" in source_config:
                    verify_config["secret"] = source_config["secret"]

                inbound_registry.register(path, normalizer_key, verify_config or None)
                logger.info("Loaded inbound endpoint: %s → %s", source_name, path)
            except Exception as exc:
                logger.error("Failed to load inbound %s: %s", source_name, exc)
