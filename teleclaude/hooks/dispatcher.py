"""Event dispatcher — routes events to matching contract targets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent

if TYPE_CHECKING:
    from teleclaude.hooks.handlers import HandlerRegistry
    from teleclaude.hooks.registry import ContractRegistry


class EnqueueWebhook(Protocol):
    """Callable protocol for enqueueing external webhook deliveries."""

    async def __call__(
        self,
        *,
        contract_id: str,
        event_json: str,
        target_url: str,
        target_secret: str | None,
    ) -> None: ...


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

    async def dispatch(self, event: HookEvent) -> None:
        """Match event against contracts and deliver to targets."""
        matches = self._contracts.match(event)
        if not matches:
            return

        for contract in matches:
            target = contract.target
            if target.handler:
                handler = self._handlers.get(target.handler)
                if handler:
                    try:
                        await handler(event)  # type: ignore[operator]  # handler is Callable, pyright can't see HandlerRegistry yet
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
                logger.warning("Contract %s matched but has no handler or URL", contract.id)
