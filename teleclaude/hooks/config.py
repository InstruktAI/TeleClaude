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


def _parse_contract_criteria(contract_data: dict[str, Any]) -> tuple[
    PropertyCriterion | None,
    PropertyCriterion | None,
    dict[str, PropertyCriterion],
]:
    """Split raw contract criteria into source, type, and property buckets."""
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
    return source_criterion, type_criterion, properties


def _build_config_contract(sub: dict[str, Any]) -> Contract:
    """Build a Contract model from a config subscription entry."""
    contract_data = sub.get("contract", {})
    target_data = sub.get("target", {})
    source_criterion, type_criterion, properties = _parse_contract_criteria(contract_data)
    target = Target(
        handler=target_data.get("handler"),
        url=target_data.get("url"),
        secret=target_data.get("secret"),
    )
    return Contract(
        id=sub["id"],
        target=target,
        source_criterion=source_criterion,
        type_criterion=type_criterion,
        properties=properties,
        source="config",
    )


def _resolve_inbound_registration(
    source_name: str,
    source_config: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None]:
    """Resolve an inbound endpoint definition from config."""
    path = source_config.get("path")
    if not path:
        path = f"/hooks/inbound/{source_name}"
        logger.info("Inbound path derived from source name: %s -> %s", source_name, path)
    normalizer_key = source_config.get("normalizer") or source_name
    verify_config = {
        key: source_config[key]
        for key in ("verify_token", "secret")
        if key in source_config
    }
    return path, normalizer_key, verify_config or None


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
    failed_subscriptions = 0
    for sub in subscriptions:
        try:
            contract = _build_config_contract(sub)
            await contract_registry.register(contract)
            logger.info("Loaded config contract: %s", contract.id)
        except (KeyError, TypeError, ValueError) as exc:
            failed_subscriptions += 1
            logger.error("Failed to load subscription %s: %s", sub.get("id", "?"), exc, exc_info=True)

    total_subscriptions = len(subscriptions)
    logger.info(
        "Loaded %s of %s subscriptions (%s failed)",
        total_subscriptions - failed_subscriptions,
        total_subscriptions,
        failed_subscriptions,
    )

    # Load inbound endpoints
    if inbound_registry:
        inbound = hooks_config.get("inbound", {})
        for source_name, source_config in inbound.items():
            try:
                path, normalizer_key, verify_config = _resolve_inbound_registration(source_name, source_config)
                inbound_registry.register(path, normalizer_key, verify_config)
                logger.info("Loaded inbound endpoint: %s → %s", source_name, path)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.error("Failed to load inbound %s: %s", source_name, exc, exc_info=True)
