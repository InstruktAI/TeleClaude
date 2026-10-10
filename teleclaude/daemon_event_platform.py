"""Event platform and webhook service mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import ResponseError

from teleclaude.config.machine import config
from teleclaude.core.event_bus import RedisStreamsClient, configure_event_bus
from teleclaude.core.integration.event_bound_maintenance import build_event_bound_maintenance_consumer
from teleclaude.core.integration.incident_alerts import build_incident_alerts_consumer
from teleclaude.core.integration.subscribed_domain_events import build_subscribed_domain_events_consumer
from teleclaude.core.integration.trigger_consumer import build_integration_trigger_consumer
from teleclaude.core.next_machine.lifecycle_router import build_lifecycle_router_consumer
from teleclaude.core.next_machine.runtime.clock import TaskScheduleClock
from teleclaude.core.procedure_routing import build_procedure_activation_consumer
from teleclaude.core.reconciliation import FleetCapabilityMap, contraction_answer_from_live_map
from teleclaude.events import (
    Consumer,
    ConsumerRuntime,
    EventCatalog,
    EventDB,
    EventLevel,
    EventProcessor,
    EventProducer,
    EventVisibility,
    build_default_catalog,
    configure_producer,
    get_event_db,
)
from teleclaude.events.correlation import CorrelationConfig, build_correlation_consumer
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.envelope_facts import EnvelopeFactResolver
from teleclaude.events.processor import CONSUMER_GROUP as EVENT_PROCESSOR_GROUP
from teleclaude.events.processor import STREAM_NAME as PLATFORM_STREAM_NAME
from teleclaude.events.references import ComputerRef
from teleclaude.events.schemas.system import DaemonRestarted, DaemonRestartedData
from teleclaude.events.wire import PLATFORM_ENTRY_CODEC, LegacyFacts
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.relay_delivery import RelayDeliveryPipeline
from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event
from teleclaude.services.project_catalog.ownership import load_project_ownership_index
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.lifecycle import DaemonLifecycle

logger = get_logger(__name__)
_EVENT_DB_REQUIRED_FOR_PIPELINE_CONTEXT = "_build_pipeline_context always runs after _init_event_db_storage"
_RELAY_DELIVERY_PROCESSOR_NAME = "relay-delivery"
_RELAY_DELIVERY_GROUP_PREFIX = "relay-delivery-"
_RELAY_DELIVERY_CONSUMER_SUFFIX = "-relay-"
_RELAY_DELIVERY_TASK_NAME = "relay-delivery-processor"
_RELAY_DELIVERY_LOG_TASK_NAME = "relay_delivery_processor"
_RELAY_DELIVERY_STARTED_EVENT = "Relay delivery processor started"
_RETIRED_GROUP_TEMPLATE = "{group}-{computer}"
_RETIRED_GROUP_DESTROYED_EVENT = "Retired system pipeline consumer group destroyed"
_RETIRED_GROUP_ABSENT_EVENT = "No stream yet; no retired system pipeline consumer group to destroy"
_EVENT_CONSUMERS_TASK_NAME = "event-consumers"
_EVENT_CONSUMERS_LOG_TASK_NAME = "event_consumers"
_EVENT_CONSUMERS_STARTED_EVENT = "Event consumer runtime started"
_API_SERVER_ATTRIBUTE = "api_server"
_API_APP_ATTRIBUTE = "app"
_INBOUND_ROUTES_INSTALLED_EVENT = "Inbound endpoints installed on the ingress computer"
_INBOUND_ROUTES_UNAVAILABLE_EVENT = "API app or event producer unavailable; inbound endpoints are not installed"
_RELAY_DELIVERY_NO_REDIS_EVENT = "Event Redis client unavailable; relayed external events are not delivered here"


@dataclass
class _EventPlatformStatus:
    redis_configured: bool
    redis_reachable: bool | None = None
    pending_recovery_progress: str = "not_started"


class _DaemonEventPlatformMixin:  # pyright: ignore[reportUnusedClass]
    """Event platform and webhook service methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        client: AdapterClient
        lifecycle: DaemonLifecycle
        _event_db: EventDB | None
        _fleet_capability_map_provider: Callable[[], FleetCapabilityMap] | None
        _event_catalog: EventCatalog | None
        _event_producer: EventProducer | None
        _event_redis_client: object | None
        _event_platform_status: _EventPlatformStatus
        _event_consumers_task: asyncio.Task[object] | None
        _relay_delivery_task: asyncio.Task[object] | None
        _internal_event_bus_task: asyncio.Task[object] | None
        _task_schedule_clock_task: asyncio.Task[object] | None
        _hook_dispatcher: HookDispatcher | None
        cache: DaemonCache

        def _log_background_task_exception(self, task_name: str) -> Callable[[asyncio.Task[object]], None]: ...

    async def _init_event_db_storage(self) -> None:
        """Initialize event storage."""
        self._event_db = await get_event_db()
        logger.info("EventDB initialized")

    async def _get_event_redis_client(self) -> object | None:
        """Return the Redis client backing the event platform."""
        redis_adapter = self.client.transport
        if not isinstance(redis_adapter, RedisTransport):
            return None
        return await redis_adapter._get_redis()

    def _live_capability_map(self) -> FleetCapabilityMap | None:
        """The daemon's current fleet capability map; none until the cluster bridge is attached."""
        provider = self._fleet_capability_map_provider
        return provider() if provider is not None else None

    def _configure_event_producer(self, redis_client: object) -> EventProducer:
        """Build and register the event producer."""

        resolver = EnvelopeFactResolver(session_id=lambda: None, ownership_index=load_project_ownership_index)
        event_producer = EventProducer(
            redis_client=redis_client,
            fact_resolver=resolver,
            contraction_answer=contraction_answer_from_live_map(self._live_capability_map),
        )
        configure_producer(event_producer)
        logger.info("EventProducer configured")
        return event_producer

    def _build_integration_trigger(self) -> Consumer:
        """Create the integration trigger consumer."""
        from teleclaude.core.integration_bridge import spawn_integrator_session  # startup boundary

        return build_integration_trigger_consumer(spawn_integrator_session)

    def _event_consumers(self) -> list[Consumer]:
        """The platform's own reactions to events, each an independent consumer on this computer."""
        assert self._event_db is not None  # initialized by _start_event_platform_prepare
        assert self._event_producer is not None  # configured by _start_event_platform_prepare
        assert self._event_catalog is not None  # built by _start_event_platform_prepare
        return [
            self._build_integration_trigger(),
            build_lifecycle_router_consumer(),
            build_procedure_activation_consumer(),
            build_event_bound_maintenance_consumer(),
            build_correlation_consumer(self._event_db, self._event_producer, CorrelationConfig()),
            build_incident_alerts_consumer(self._event_db, self._event_catalog),
            build_subscribed_domain_events_consumer(self._event_db, self._event_catalog),
        ]

    async def _destroy_retired_system_group(self, redis_client: object) -> None:
        """Destroy this computer's consumer group of the retired system pipeline, discarding its pending entries."""
        group = _RETIRED_GROUP_TEMPLATE.format(group=EVENT_PROCESSOR_GROUP, computer=config.computer.name)
        try:
            await cast(Any, redis_client).xgroup_destroy(PLATFORM_STREAM_NAME, group)
        except ResponseError:
            # A stream that does not exist yet has no retired group to destroy.
            logger.info(_RETIRED_GROUP_ABSENT_EVENT, group=group)
            return
        logger.info(_RETIRED_GROUP_DESTROYED_EVENT, group=group)

    def _start_event_consumers_runtime(self, redis_client: object) -> None:
        """Start the consumer runtime: one ordered reader of the platform stream per declared consumer."""
        assert self._event_db is not None  # initialized by _start_event_platform_prepare
        consumers = self._event_consumers()
        runtime = ConsumerRuntime(
            consumers,
            redis_client=redis_client,
            db=self._event_db,
            computer=config.computer.name,
        )
        self._event_consumers_task = asyncio.create_task(
            runtime.run(self.shutdown_event), name=_EVENT_CONSUMERS_TASK_NAME
        )
        self._event_consumers_task.add_done_callback(
            self._log_background_task_exception(_EVENT_CONSUMERS_LOG_TASK_NAME)
        )
        logger.info(_EVENT_CONSUMERS_STARTED_EVENT, consumers=[consumer.name for consumer in consumers])

    def _start_relay_delivery_consumer(self, dispatcher: HookDispatcher) -> None:
        """Start the per-computer group that delivers relayed external events to the local hook dispatcher."""
        redis_client = self._event_redis_client
        if redis_client is None:
            logger.warning(_RELAY_DELIVERY_NO_REDIS_EVENT)
            return
        computer_label = config.computer.name
        reliability = config.event_reliability
        processor = EventProcessor(
            redis_client=redis_client,
            pipeline=RelayDeliveryPipeline(dispatcher),
            codec=PLATFORM_ENTRY_CODEC,
            declared_name=_RELAY_DELIVERY_PROCESSOR_NAME,
            group=_RELAY_DELIVERY_GROUP_PREFIX + computer_label,
            consumer_name=computer_label + _RELAY_DELIVERY_CONSUMER_SUFFIX + str(os.getpid()),
            idle_threshold_ms=reliability.idle_threshold_ms,
            max_attempts=reliability.max_attempts,
            sweep_interval_ms=reliability.sweep_interval_ms,
            dlq_destination=reliability.dlq_destination,
        )
        self._relay_delivery_task = asyncio.create_task(
            processor.start(self.shutdown_event), name=_RELAY_DELIVERY_TASK_NAME
        )
        self._relay_delivery_task.add_done_callback(self._log_background_task_exception(_RELAY_DELIVERY_LOG_TASK_NAME))
        logger.info(_RELAY_DELIVERY_STARTED_EVENT, computer=computer_label)

    def _start_internal_event_bus(self, redis_client: object) -> None:
        """Configure and start the daemon role's internal EventBus consumer."""
        bus = configure_event_bus(role="daemon", redis_client=cast(RedisStreamsClient, redis_client))
        self._internal_event_bus_task = asyncio.create_task(
            bus.start(self.shutdown_event),
            name="internal-event-bus",
        )
        self._internal_event_bus_task.add_done_callback(self._log_background_task_exception("internal_event_bus"))
        logger.info("Internal EventBus started", role="daemon")

    async def _emit_daemon_restarted_event(
        self,
        event_producer: EventProducer,
        computer_label: str,
    ) -> None:
        """Emit the daemon-restarted infrastructure event."""
        await event_producer.emit(
            DaemonRestarted(
                subject=ComputerRef(computer_label),
                home=EventHomeMarker.NONE,
                data=DaemonRestartedData(computer=computer_label, pid=os.getpid()),
            ),
            LegacyFacts(
                producer="daemon",
                level=EventLevel.INFRASTRUCTURE,
                domain="system",
                visibility=EventVisibility.CLUSTER,
                description=f"Daemon restarted on {computer_label}",
            ),
        )
        logger.info("Event 'teleclaude.system.daemon.restarted' emitted")

    def _start_task_schedule_clock(self, event_producer: EventProducer) -> None:
        """Start the workflow schedule minute clock."""
        self._task_schedule_clock_task = asyncio.create_task(
            TaskScheduleClock(event_producer).run(self.shutdown_event),
            name="task-schedule-clock",
        )
        self._task_schedule_clock_task.add_done_callback(self._log_background_task_exception("task_schedule_clock"))
        logger.info("Task schedule minute clock started")

    async def _start_event_platform_prepare(self) -> None:
        """Prepare the event platform's producer side before the API socket binds.

        Redis is required. If it is unreachable, the daemon must not continue —
        downstream code (operations, integration, signals) emits events
        unconditionally and treating a missing producer as "degraded but
        running" hides real failures behind ERROR-log spam.

        Builds the producer, pipeline, and context only. Consumer tasks (the
        stream processor, the scheduler minute-clock, and everything downstream
        of them) start later, in ``_start_event_consumers``, once the API socket
        is bound — a consumer live before the socket exists can self-call the
        daemon's own API and fail with a connect error.
        """
        redis_configured = bool(config.redis.url)
        self._event_platform_status = _EventPlatformStatus(redis_configured=redis_configured)
        await self._init_event_db_storage()
        event_catalog = build_default_catalog()
        redis_client = await self._get_event_redis_client()
        if redis_client is None:
            raise RuntimeError(
                f"Event platform startup failed: Redis unreachable (redis_configured={redis_configured})"
            )

        self._event_platform_status.redis_reachable = True
        self._event_platform_status.pending_recovery_progress = "processor_starting"
        self._start_internal_event_bus(redis_client)
        event_producer = self._configure_event_producer(redis_client)
        self._event_catalog = event_catalog
        self._event_producer = event_producer
        self._event_redis_client = redis_client

    async def _start_event_consumers(self) -> None:
        """Start the event platform's consumer tasks after the API socket is bound."""
        redis_client = self._event_redis_client
        event_producer = self._event_producer
        assert event_producer is not None  # built by _start_event_platform_prepare
        await self._destroy_retired_system_group(redis_client)
        computer_label = config.computer.name
        self._start_event_consumers_runtime(redis_client)
        self._event_platform_status.pending_recovery_progress = "processor_started"
        logger.info(
            "event_platform_redis_available: pending recovery scheduled",
            redis_configured=self._event_platform_status.redis_configured,
            redis_reachable=True,
            pending_recovery_progress=self._event_platform_status.pending_recovery_progress,
        )
        await self._emit_daemon_restarted_event(event_producer, computer_label)
        self._start_task_schedule_clock(event_producer)

    async def _init_webhook_service(self) -> None:
        """Initialize the hook service: register the built-in handlers and contracts and start the dispatcher's feeds."""

        contract_registry = ContractRegistry()
        handler_registry = HandlerRegistry()
        dispatcher = HookDispatcher(contract_registry, handler_registry)
        self._hook_dispatcher = dispatcher

        # Built-in inbound WhatsApp handling (global subscription handler).
        handler_registry.register("whatsapp_inbound", handle_whatsapp_event)
        contract_registry.register(
            Contract(
                id="builtin-whatsapp-inbound",
                target=Target(handler="whatsapp_inbound"),
                source_criterion=PropertyCriterion(match="whatsapp"),
                type_criterion=PropertyCriterion(pattern="message.*"),
            )
        )

        self._start_relay_delivery_consumer(dispatcher)
        self._install_inbound_routes()

        logger.info("Webhook service initialized")

    def _install_inbound_routes(self) -> None:
        """Mount the inbound endpoints on the API app, on the ingress computer only."""
        if not config.computer.is_ingress_node:
            return
        app = getattr(getattr(self.lifecycle, _API_SERVER_ATTRIBUTE, None), _API_APP_ATTRIBUTE, None)
        producer = self._event_producer
        if app is None or producer is None:
            logger.warning(_INBOUND_ROUTES_UNAVAILABLE_EVENT)
            return
        install_inbound_routes(app, producer)
        logger.info(_INBOUND_ROUTES_INSTALLED_EVENT)
