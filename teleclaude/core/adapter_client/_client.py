"""Core adapter runtime composing channel, output, and remote mixins."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.config.machine import config
from teleclaude.config.validation import AvailabilityState
from teleclaude.core.degradation import DegradationRecord, DegradedComponent
from teleclaude.core.delivery import resolve_destination
from teleclaude.core.events import SystemCommand, SystemCommandContext
from teleclaude.core.models import MessageMetadata
from teleclaude.transport.redis_transport import RedisTransport

from ._channels import _ChannelsMixin
from ._output import _OutputMixin
from ._remote import _RemoteMixin

if TYPE_CHECKING:
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.events import AgentEventContext
    from teleclaude.core.models import Session
    from teleclaude.core.runtime_readiness import RuntimeReadiness
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

# The four destination-addressed delivery methods (base_adapter.py); every
# other UiAdapter/BaseAdapter method dispatched through _route_to_ui stays
# session-addressed. See local/projects/teleclaude/design/architecture/adapter-client
# (Destination-Addressed Seam invariant).
_ADAPTER_START_FAILED = "failed to start: {error}; it stays down until the daemon restarts"
_DESTINATION_ADDRESSED_METHODS = frozenset({"send_message", "edit_message", "delete_message", "send_file"})


class AdapterStatus(StrEnum):
    """Outcome of evaluating a configured adapter at startup."""

    DISABLED = "disabled"  # enabled: false — not started, not surfaced
    MISCONFIGURED = "misconfigured"  # enabled but required credentials missing
    ERROR = "error"  # enabled + configured, but start()/connection failed
    OK = "ok"  # started and registered


@dataclass(frozen=True)
class AdapterStatusReport:
    """Per-adapter startup outcome, queryable for user surfacing."""

    status: AdapterStatus
    missing: tuple[str, ...] = ()  # unconfigured credential labels (MISCONFIGURED)
    error: str | None = None  # failure detail (ERROR)


_OUTPUT_SUMMARY_MIN_INTERVAL_S = 2.0
_OUTPUT_SUMMARY_IDLE_THRESHOLD_S = 2.0


class AdapterRuntime(_OutputMixin, _ChannelsMixin, _RemoteMixin):
    """Runtime host for adapter lifecycle and shared infrastructure.

    Manages UI adapters (Telegram, Discord, WhatsApp) and transport services
    (Redis), owning startup/shutdown, registry, and shared execution plumbing.
    Concrete UI delivery policy belongs to UiAdapter subclasses, not here.

    Routing helpers execute explicit UI operations across selected adapters.
    Narrow flows must not provision unrelated UI lanes.
    """

    def __init__(
        self,
        task_registry: "TaskRegistry",
        runtime_readiness: "RuntimeReadiness",
        degradations: DegradationRecord,
    ) -> None:
        """Initialize adapter runtime.

        Args:
            task_registry: Daemon-owned TaskRegistry for tracking and supervising background tasks
            degradations: Daemon-owned record in which a UI adapter that fails to start is marked degraded
        """
        self.task_registry = task_registry
        self.runtime_readiness = runtime_readiness
        self.degradations = degradations
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance (UI adapters only)
        # Redis is a transport, not an adapter: kept off the adapter registry so
        # adapter counts, UI resolution, and headless detection stay honest.
        self.transport: RedisTransport | None = None
        self.cache: DaemonCache | None = None
        # Per-adapter startup outcome (disabled/misconfigured/error/ok), surfaced to the user.
        self.adapter_status: dict[str, AdapterStatusReport] = {}
        # Direct handler for agent events (set by daemon, replaces event bus for AGENT_EVENT)
        self.agent_event_handler: Callable[[AgentEventContext], Awaitable[None]] | None = None
        self.agent_coordinator: AgentCoordinator | None = None
        self.system_command_handler: Callable[[SystemCommandContext], Awaitable[None]] | None = None
        # Per-session lock for channel provisioning (prevents concurrent ensure_channel races)
        self._channel_ensure_locks: dict[str, asyncio.Lock] = {}

    async def dispatch_system_command(self, context: SystemCommandContext) -> None:
        """Route each system command directly to its owning runtime capability."""
        if context.command == SystemCommand.SESSION_OUTPUT_STOPPED:
            for _adapter_type, adapter in self._ui_adapters():
                if isinstance(adapter, DiscordAdapter):
                    await adapter.handle_system_command(context)
            return
        if self.system_command_handler is not None:
            await self.system_command_handler(context)

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

    def _resolve_ui_targets(self, include_adapters: set[str] | None = None) -> list[tuple[str, UiAdapter]]:
        """Registered UI adapters, optionally narrowed to ``include_adapters``.

        The single resolver for "which UI adapters does this operation target".
        An empty result is normal (headless, or the targeted adapter is disabled/
        absent) and callers treat it as a no-op rather than an error.
        """
        targets = self._ui_adapters()
        if include_adapters is not None:
            targets = [(t, a) for t, a in targets if t in include_adapters]
        return targets

    async def _broadcast_to_ui_adapters(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
        include_adapters: set[str] | None = None,
    ) -> list[tuple[str, object]]:
        """Send operation to the selected UI adapters sequentially.

        Serialized (not parallel) to prevent concurrent adapter_metadata blob
        writes from clobbering each other — each adapter reads the previous
        adapter's writes before persisting its own changes.
        """
        ui_adapters = self._resolve_ui_targets(include_adapters)
        if not ui_adapters:
            logger.debug("No UI adapters available for %s (session %s)", operation, session.session_id)
            return []

        output: list[tuple[str, object]] = []
        for adapter_type, adapter in ui_adapters:
            result = await self._run_ui_lane(session, adapter_type, adapter, task_factory)
            output.append((adapter_type, result))

        return output

    async def start(self) -> None:
        """Evaluate and start each UI adapter through one three-state path.

        Per adapter, surfaced once here and never crashing the daemon:
        - DISABLED        (enabled: false)            → skipped silently
        - MISCONFIGURED   (enabled, missing creds)    → WARNING; not started, not routed
        - ERROR           (configured, start failed)  → ERROR; left unregistered, marked degraded
        - OK                                          → started and registered

        Outcomes are recorded in self.adapter_status, and a failed start is marked in
        self.degradations so the daemon's health and status report it. The Redis
        transport is required infrastructure (not a UI adapter) and is started
        separately; its failure remains fatal.
        """
        adapter_specs: list[tuple[str, Callable[[], BaseAdapter]]] = [
            (
                "discord",
                lambda: DiscordAdapter(self, task_registry=self.task_registry),
            ),
            (
                "telegram",
                lambda: TelegramAdapter(self, task_registry=self.task_registry),
            ),
            ("whatsapp", lambda: WhatsAppAdapter(self)),
        ]
        for name, factory in adapter_specs:
            availability = config.availability(name)
            if availability.state in (AvailabilityState.NOT_APPLICABLE, AvailabilityState.DISABLED):
                self.adapter_status[name] = AdapterStatusReport(AdapterStatus.DISABLED)
                continue
            missing = list(availability.missing_fields)
            if missing:
                logger.warning("Adapter %s is enabled but not configured: missing %s", name, ", ".join(missing))
                self.adapter_status[name] = AdapterStatusReport(AdapterStatus.MISCONFIGURED, missing=tuple(missing))
                continue
            logger.info("[STARTUP] Starting %s adapter (usually 2-8s)", name)
            try:
                adapter = factory()
                await adapter.start()
            except Exception as exc:
                logger.error("Adapter %s is configured but failed to start: %s", name, exc)
                self.adapter_status[name] = AdapterStatusReport(AdapterStatus.ERROR, error=str(exc))
                self.degradations.mark(
                    DegradedComponent.UI_ADAPTER,
                    _ADAPTER_START_FAILED.format(error=exc),
                    subject=name,
                )
                continue
            self.adapters[name] = adapter
            self.adapter_status[name] = AdapterStatusReport(AdapterStatus.OK)
            logger.info("Started %s adapter", name)

        # Redis transport (NOT an adapter — required infrastructure; failure is fatal)
        logger.info("[STARTUP] Starting Redis transport (usually <1s)")
        redis = RedisTransport(self, task_registry=self.task_registry)
        await redis.start()
        self.transport = redis
        logger.info("Started redis transport")

        if not self.adapters:
            logger.info("Daemon running in TUI-only/headless mode (no UI adapters started)")
        else:
            logger.info("Started %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

    async def stop(self) -> None:
        """Stop all registered adapters and the transport."""
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

        # Transport is not in the adapter registry; stop it explicitly.
        if self.transport is not None:
            logger.info("Stopping redis transport...")
            try:
                await self.transport.stop()
            except Exception as exc:
                logger.error("Failed to stop redis transport: %s", exc)

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
        ensure_channels: bool = True,
        **kwargs: object,
    ) -> object:
        """Send operation to the selected UI adapters, returning the entry point result.

        Matching UI adapters receive the operation. The return value
        comes from the adapter matching session.last_input_origin (if it's a
        UI adapter), otherwise from the first successful adapter.

        Channel provisioning prepares the selected adapters. Narrow routing
        flows must pass explicit include_adapters rather than relying on
        implicit all-adapter fanout.
        """
        if ensure_channels:
            session = await self.ensure_ui_channels(session, include_adapters=include_adapters)

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            if method in _DESTINATION_ADDRESSED_METHODS:
                metadata = kwargs.get("metadata")
                destination = resolve_destination(
                    lane_session,
                    adapter.ADAPTER_KEY,
                    metadata=metadata if isinstance(metadata, MessageMetadata) else None,
                )
                return cast(Awaitable[object], getattr(adapter, method)(destination, *args, **kwargs))
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
            if isinstance(result, Exception | type(None)):
                continue
            if first_result is None:
                first_result = result
            if adapter_type == entry_point:
                entry_point_result = result

        return entry_point_result if entry_point_result is not None else first_result


AdapterClient = AdapterRuntime
