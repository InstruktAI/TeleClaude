"""Sanitized lifecycle observations for outbound provider operations."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

PROVIDER_OBSERVATION_EVENT = "outbound_provider_observation"
OPERATION_ID_FIELD = "operation_id"
OUTCOME_FIELD = "outcome"
PROVIDER_FIELD = "provider"
CLIENT_CLEANUP_FIELD = "client_cleanup"
CLIENT_CLEANUP_CLOSED_ONCE = "closed_once"


class Provider(StrEnum):
    """Closed provider vocabulary for outbound delivery observations."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class ProviderOutcome(StrEnum):
    """Closed terminal-state vocabulary for outbound delivery."""

    ACCEPTED = "accepted"
    SENT = "sent"
    REJECTED = "rejected"
    MISSING_CONFIG = "missing_config"


def new_operation_id() -> str:
    """Create one correlation identifier for a provider operation."""
    return str(uuid4())


def client_cleanup_details(client_cleanup_completed: bool) -> dict[str, str]:
    """Return cleanup evidence only after a client has actually closed."""
    if not client_cleanup_completed:
        return {}
    return {CLIENT_CLEANUP_FIELD: CLIENT_CLEANUP_CLOSED_ONCE}


def observe_provider(provider: Provider, outcome: ProviderOutcome, operation_id: str, **details: object) -> None:
    """Record provider progress without including message content or credentials."""
    logger.info(
        PROVIDER_OBSERVATION_EVENT,
        **{PROVIDER_FIELD: provider.value, OUTCOME_FIELD: outcome.value, OPERATION_ID_FIELD: operation_id, **details},
    )
