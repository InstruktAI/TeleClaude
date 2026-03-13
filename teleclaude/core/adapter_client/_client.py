"""Core AdapterClient class composing channel, output, and remote mixins."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.config import config
from teleclaude.transport.redis_transport import RedisTransport

from ._channels import _ChannelsMixin
from ._output import _OutputMixin
from ._remote import _RemoteMixin

if TYPE_CHECKING:
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.events import AgentEventContext
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

_OUTPUT_SUMMARY_MIN_INTERVAL_S = 2.0
_OUTPUT_SUMMARY_IDLE_THRESHOLD_S = 2.0


class AdapterClient(_OutputMixin, _ChannelsMixin, _RemoteMixin):
    """Unified interface for multi-adapter operations.

    Manages UI adapters (Telegram, Discord) and transport services (Redis),
    providing a clean, boundary-agnostic API. Owns the lifecycle of registered
    components.

    Routing model: all UI adapters receive output unconditionally. Channel
    provisioning (ensure_channel) determines which adapters participate —
    not the routing layer. The entry point (last_input_origin) is bookkeeping
    for response routing, not a routing decision.
    """

    def __init__(self, task_registry: "TaskRegistry | None" = None) -> None:
        """Initialize AdapterClient.

        Args:
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        self.task_registry = task_registry
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance
        self.is_shutting_down = False
        # Direct handler for agent events (set by daemon, replaces event bus for AGENT_EVENT)
        self.agent_event_handler: Callable[[AgentEventContext], Awaitable[None]] | None = None
        self.agent_coordinator: AgentCoordinator | None = None
        # Per-session lock for channel provisioning (prevents concurrent ensure_channel races)
        self._channel_ensure_locks: dict[str, asyncio.Lock] = {}

    def mark_shutting_down(self) -> None:
        """Mark client as shutting down to suppress adapter restarts."""
        self.is_shutting_down = True

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter) -> None:
        """Manually register an adapter (for testing).

        Args:
            adapter_type: Adapter type name ('telegram', 'redis', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    def _ui_adapters(self) -> list[tuple[str, UiAdapter]]:
        return [
            (adapter_type, adapter) for adapter_type, adapter in self.adapters.items() if isinstance(adapter, UiAdapter)
        ]

    def any_adapter_wants_threaded_output(self) -> bool:
        """Return True when any registered UI adapter uses threaded output mode."""
        return any(adapter.THREADED_OUTPUT for _, adapter in self._ui_adapters())

    async def _broadcast_to_ui_adapters(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
        include_adapters: set[str] | None = None,
    ) -> list[tuple[str, object]]:
        """Send operation to all UI adapters sequentially.

        Serialized (not parallel) to prevent concurrent adapter_metadata blob
        writes from clobbering each other — each adapter reads the previous
        adapter's writes before persisting its own changes.
        """
        ui_adapters = self._ui_adapters()
        if include_adapters is not None:
            ui_adapters = [
                (adapter_type, adapter) for adapter_type, adapter in ui_adapters if adapter_type in include_adapters
            ]
        if not ui_adapters:
            logger.warning("No UI adapters available for %s (session %s)", operation, session.session_id)
            return []

        output: list[tuple[str, object]] = []
        for adapter_type, adapter in ui_adapters:
            result = await self._run_ui_lane(session, adapter_type, adapter, task_factory)
            output.append((adapter_type, result))

        return output

    async def start(self) -> None:
        """Start adapters and register ONLY successful ones.

        INVARIANT: self.adapters contains ONLY successfully started adapters.

        This eliminates ALL defensive checks because:
        - Adapter in registry → start() succeeded → internal state is valid
        - Metadata exists → contract guarantees it's valid
        - Trust the contract, let bugs fail fast

        Raises:
            Exception: If adapter start() fails (daemon crashes - this is intentional)
            ValueError: If no adapters started
        """
        # Discord adapter (guard for tests that patch config with older/minimal objects)
        discord_cfg = getattr(config, "discord", None)
        if discord_cfg is not None and bool(getattr(discord_cfg, "enabled", False)):
            discord = DiscordAdapter(self, task_registry=self.task_registry)
            await discord.start()  # Raises if fails -> daemon crashes
            self.adapters["discord"] = discord  # Register ONLY after success
            logger.info("Started discord adapter")

        # Telegram adapter
        # Check for env token presence (adapter authenticates from env)
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram = TelegramAdapter(self)
            await telegram.start()  # Raises if fails → daemon crashes
            self.adapters["telegram"] = telegram  # Register ONLY after success
            logger.info("Started telegram adapter")

        whatsapp_cfg = getattr(config, "whatsapp", None)
        if (
            whatsapp_cfg is not None
            and bool(getattr(whatsapp_cfg, "enabled", False))
            and getattr(whatsapp_cfg, "phone_number_id", None)
            and getattr(whatsapp_cfg, "access_token", None)
        ):
            whatsapp = WhatsAppAdapter(self)
            await whatsapp.start()
            self.adapters["whatsapp"] = whatsapp
            logger.info("Started whatsapp adapter")

        # Redis adapter
        if config.redis.enabled:
            redis = RedisTransport(self, task_registry=self.task_registry)
            await redis.start()  # Raises if fails → daemon crashes
            self.adapters["redis"] = redis  # Register ONLY after success
            logger.info("Started redis transport")

        # Validate at least one adapter started
        if not self.adapters:
            raise ValueError("No adapters started - check config.yml and .env")

        logger.info("Started %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

    async def stop(self) -> None:
        """Stop all registered adapters."""
        tasks = []
        for adapter_type, adapter in self.adapters.items():
            logger.info("Stopping %s adapter...", adapter_type)
            tasks.append(adapter.stop())

        # Stop all adapters in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any failures
        for adapter_type, result in zip(self.adapters.keys(), results):
            if isinstance(result, Exception):
                logger.error("Failed to stop %s adapter: %s", adapter_type, result)
            else:
                logger.info("%s adapter stopped", adapter_type)

    async def _fanout_excluding(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
        *,
        exclude: str | None = None,
    ) -> None:
        """Send operation to all UI adapters except one (best-effort).

        Used for echo prevention: when a user types in one adapter, broadcast
        the input to all other UI adapters without echoing it back to the source.

        Args:
            session: Session object
            operation: Operation name for logging
            task_factory: Function that takes adapter and returns awaitable
            exclude: Adapter type to skip. Uses session.last_input_origin if not provided.
        """
        skip = exclude or session.last_input_origin

        tasks: list[tuple[str, Awaitable[object]]] = []
        for adapter_type, adapter in self.adapters.items():
            if adapter_type == skip:
                continue
            if isinstance(adapter, UiAdapter):
                tasks.append((adapter_type, self._run_ui_lane(session, adapter_type, adapter, task_factory)))

        if tasks:
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

            for (adapter_type, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "UI adapter %s failed %s for session %s: %s",
                        adapter_type,
                        operation,
                        session.session_id,
                        result,
                    )
                else:
                    logger.debug(
                        "UI adapter %s completed %s for session %s", adapter_type, operation, session.session_id
                    )

    async def _route_to_ui(
        self,
        session: "Session",
        method: str,
        *args: object,
        include_adapters: set[str] | None = None,
        **kwargs: object,
    ) -> object:
        """Send operation to all UI adapters, returning the entry point result.

        All UI adapters receive the operation in parallel. The return value
        comes from the adapter matching session.last_input_origin (if it's a
        UI adapter), otherwise from the first successful adapter.

        Channel provisioning (ensure_channel) determines which adapters
        participate — not the routing layer.
        """
        session = await self.ensure_ui_channels(session)

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(Awaitable[object], getattr(adapter, method)(lane_session, *args, **kwargs))

        entry_point = session.last_input_origin
        logger.debug(
            "[ROUTING] Fanout: session=%s method=%s entry_point=%s",
            session.session_id,
            method,
            entry_point,
        )
        results = await self._broadcast_to_ui_adapters(session, method, make_task, include_adapters=include_adapters)

        # Prefer result from entry point adapter, fall back to first success
        entry_point_result: object = None
        first_result: object = None
        for adapter_type, result in results:
            if isinstance(result, (Exception, type(None))):
                continue
            if first_result is None:
                first_result = result
            if adapter_type == entry_point:
                entry_point_result = result

        return entry_point_result if entry_point_result is not None else first_result
