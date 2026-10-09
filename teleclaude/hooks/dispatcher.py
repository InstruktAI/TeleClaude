"""Event dispatcher — routes events to the handlers of matching contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent

if TYPE_CHECKING:
    from teleclaude.hooks.handlers import HandlerRegistry
    from teleclaude.hooks.registry import ContractRegistry


logger = get_logger(__name__)


class HookDispatcher:
    """Routes events to the handlers of matching contracts."""

    def __init__(self, contract_registry: ContractRegistry, handler_registry: HandlerRegistry) -> None:
        self._contracts = contract_registry
        self._handlers = handler_registry

    async def dispatch(self, event: HookEvent) -> None:
        """Match event against contracts and call each matching contract's handler."""
        for contract in self._contracts.match(event):
            handler = self._handlers.get(contract.target.handler)
            if handler is None:
                logger.warning("Handler not found: %s", contract.target.handler)
                continue
            try:
                await handler(event, contract)
            except Exception as exc:
                logger.error(
                    "Internal handler failed",
                    handler=contract.target.handler,
                    contract_id=contract.id,
                    error=str(exc),
                    exc_info=True,
                )
