"""Event dispatcher — routes events to matching contract targets."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import ErrorEventContext, TeleClaudeEvents
from teleclaude.events.envelope import EventVisibility
from teleclaude.hooks.webhook_models import HookEvent

if TYPE_CHECKING:
    from teleclaude.hooks.handlers import HandlerRegistry
    from teleclaude.hooks.registry import ContractRegistry

EnqueueWebhook = Callable[..., Awaitable[None]]
PreMatchRefresh = Callable[[], Awaitable[None]]


logger = get_logger(__name__)


class HookDispatcher:
    """Routes events to matching contract targets."""

    def __init__(
        self,
        contract_registry: ContractRegistry,
        handler_registry: HandlerRegistry,
        enqueue_webhook: EnqueueWebhook,
    ) -> None:
        self._contracts = contract_registry
        self._handlers = handler_registry
        self._enqueue_webhook = enqueue_webhook
        self._pre_match: list[PreMatchRefresh] = []

    def register_pre_match(self, refresh: PreMatchRefresh) -> None:
        """Register a refresh hook run, in registration order, before every match.

        A failing refresher is logged and emitted as a platform error event;
        dispatch continues against whatever contracts are already cached.
        """
        self._pre_match.append(refresh)

    async def dispatch(self, event: HookEvent) -> None:
        """Refresh derived contracts, then match event against contracts and deliver to targets."""
        for refresh in self._pre_match:
            try:
                await refresh()
            except Exception as exc:
                logger.error("Pre-match refresh failed", error=str(exc), exc_info=True)
                try:
                    event_bus.emit(
                        TeleClaudeEvents.ERROR,
                        ErrorEventContext(session_id=None, message=str(exc), source="hook_dispatcher_pre_match"),
                        visibility=EventVisibility.CLUSTER,
                    )
                except Exception as emit_exc:
                    logger.error("Pre-match refresh failure event emission failed", error=str(emit_exc))

        matches = self._contracts.match(event)
        if not matches:
            return

        for contract in matches:
            target = contract.target
            if target.handler:
                handler = self._handlers.get(target.handler)
                if handler:
                    try:
                        await handler(event, contract)
                    except Exception as exc:
                        logger.error(
                            "Internal handler failed",
                            handler=target.handler,
                            contract_id=contract.id,
                            error=str(exc),
                            exc_info=True,
                        )
                else:
                    logger.warning("Handler not found: %s", target.handler)
            elif target.url:
                try:
                    await self._enqueue_webhook(
                        contract_id=contract.id,
                        event_json=event.to_json(),
                        target_url=target.url,
                        target_secret=target.secret,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to enqueue webhook",
                        contract_id=contract.id,
                        url=target.url,
                        error=str(exc),
                        exc_info=True,
                    )
            else:
                logger.warning(
                    "Contract %s matched but has no handler or URL",
                    contract.id,
                )

    async def deliver(self, event: HookEvent) -> None:
        """Compatibility alias for dispatching an event."""
        await self.dispatch(event)
