"""Contract registry — the in-memory routing table from events to handler contracts."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.hooks.matcher import match_event
from teleclaude.hooks.webhook_models import Contract, HookEvent

logger = get_logger(__name__)


class ContractRegistry:
    """Holds the contracts the daemon registers and finds the ones an event matches."""

    def __init__(self) -> None:
        self._contracts: dict[str, Contract] = {}

    def register(self, contract: Contract) -> None:
        """Register or replace a contract."""
        self._contracts[contract.id] = contract
        logger.debug("Registered contract: %s", contract.id)

    def match(self, event: HookEvent) -> list[Contract]:
        """Find all contracts matching an event."""
        return [c for c in self._contracts.values() if match_event(event, c)]
