"""Event platform and webhook service mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import ResponseError

from teleclaude.config.machine import config
from teleclaude.core.command_dispatch import run_local_command
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    SystemCommandContext,
)
from teleclaude.core.integration.ci_run_outcomes import build_ci_run_outcomes_consumer
from teleclaude.core.integration.event_bound_maintenance import build_event_bound_maintenance_consumer
from teleclaude.core.integration.incident_alerts import build_incident_alerts_consumer
from teleclaude.core.integration.subscribed_domain_events import build_subscribed_domain_events_consumer
from teleclaude.core.internal_event_envelope import INTERNAL_EVENT_STREAM
from teleclaude.core.next_machine.failed_check_bugs import build_failed_check_bugs_consumer
from teleclaude.core.next_machine.lifecycle_router import build_lifecycle_router_consumer
from teleclaude.core.next_machine.runtime.clock import TaskScheduleClock
from teleclaude.core.procedure_routing import build_procedure_activation_consumer
from teleclaude.core.reconciliation import FleetCapabilityMap, contraction_answer_from_live_map
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_assessment import AssessmentAnnouncer
from teleclaude.core.reconciliation.installation_reaction import (
    InstallationSourceReader,
    build_installation_reaction_consumer,
)
from teleclaude.core.runtime_event_consumers import RuntimeVoiceSurface, build_runtime_event_consumers
from teleclaude.core.runtime_events import INTERNAL_RUNTIME_EVENT_STREAM
from teleclaude.core.session_cleanup import terminate_session
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
from teleclaude.events.consumer_handover import prepare_internal_event_handover
from teleclaude.events.consumers import ConsumerDelivery
from teleclaude.events.correlation import CorrelationConfig, build_correlation_consumer
from teleclaude.events.envelope import EventHomeMarker, ReceivedEvent, occurrence_id
from teleclaude.events.envelope_facts import EnvelopeFactResolver
from teleclaude.events.processor import CONSUMER_GROUP as EVENT_PROCESSOR_GROUP
from teleclaude.events.processor import STREAM_NAME as PLATFORM_STREAM_NAME
from teleclaude.events.references import ComputerRef
from teleclaude.events.schemas.system import DaemonRestarted, DaemonRestartedData, RuntimeSessionStatusData
from teleclaude.events.scope import ScopedClients
from teleclaude.events.scoped_redis import close_scoped_clients, local_redis_configured, scoped_redis_clients
from teleclaude.events.wire import PLATFORM_ENTRY_CODEC, LegacyFacts
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.github_handler import GitHubCommentEvent, handle_github_event
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.hooks.normalizers.github import GITHUB_SOURCE
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.relay_delivery import RelayDeliveryPipeline
from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event
from teleclaude.memory.closure import build_memory_closure_consumer
from teleclaude.memory.transition import run_transition, run_transition_until_complete
from teleclaude.mirrors.closure import build_mirror_closure_consumer
from teleclaude.services.project_catalog.ownership import load_project_ownership_index
from teleclaude.services.project_catalog.service import registered_project_paths
from teleclaude.transport.internal_event_compat import (
    InternalEventCompatIngressData,
    SessionLifecycleContext,
    decode_compat_ingress_context,
    internal_event_entry_codec,
)
from teleclaude.types.commands import CloseSessionCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.events import ErrorEventContext
    from teleclaude.core.lifecycle import DaemonLifecycle
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

_GITHUB_COMMENT_HANDLER = "github_comment_routing"
_GITHUB_COMMENT_CONTRACT = "builtin-github-comment-routing"
logger = get_logger(__name__)

_REDIS_UNCONFIGURED_ERROR = "Event platform startup failed: config.redis.cluster.url is empty"
# A computer without its own local Redis carries its local events on the cluster Redis.
_LOCAL_REDIS_UNCONFIGURED_EVENT = "local_redis_unconfigured_local_events_on_cluster"


async def _ping_both(clients: ScopedClients[Any]) -> None:
    """Confirm each scope's Redis answers before any reader or producer relies on it."""
    for client in clients.distinct():
        await client.ping()


async def _close_both(clients: ScopedClients[Any]) -> None:
    """Close each scope's client and its owned pool."""
    await close_scoped_clients(clients)


_EVENT_DB_REQUIRED_FOR_PIPELINE_CONTEXT = "_build_pipeline_context always runs after _init_event_db_storage"
_RELAY_DELIVERY_PROCESSOR_NAME = "relay-delivery"
_RELAY_DELIVERY_GROUP_PREFIX = "relay-delivery-"
_RELAY_DELIVERY_CONSUMER_SUFFIX = "-relay-"
_RELAY_DELIVERY_TASK_NAME = "relay-delivery-processor"
_RELAY_DELIVERY_STARTED_EVENT = "Relay delivery processor started"
_RETIRED_GROUP_TEMPLATE = "{group}-{computer}"
_RETIRED_GROUP_DESTROYED_EVENT = "Retired system pipeline consumer group destroyed"
_RETIRED_GROUP_ABSENT_EVENT = "No stream yet; no retired system pipeline consumer group to destroy"
_TASK_SCHEDULE_CLOCK_TASK_NAME = "task-schedule-clock"
_ASSESSMENT_ANNOUNCER_TASK_NAME = "installation-assessment-announcer"
_ASSESSMENT_ANNOUNCER_STARTED_EVENT = "Installation assessment announcer started"
_SOURCE_READER_TASK_NAME = "installation-source-reader"
_SOURCE_READER_STARTED_EVENT = "Installation source reader started"
_EVENT_CONSUMERS_STARTED_EVENT = "Event consumer runtime started"
_MEMORY_TRANSITION_TASK_NAME = "memory-transition"
_MEMORY_TRANSITION_LOG_TASK_NAME = "memory_transition"
_MEMORY_TRANSITION_PASS_FAILED_EVENT = "memory.transition.pass_failed"
_MEMORY_TRANSITION_INCOMPLETE_EVENT = "Conversation-memory transition incomplete; retrying until complete"
_MEMORY_TRANSITION_END_REASON = "conversation_memory_transition"
_API_SERVER_ATTRIBUTE = "api_server"
_API_APP_ATTRIBUTE = "app"
_INBOUND_ROUTES_INSTALLED_EVENT = "Inbound endpoints installed on the ingress computer"
_INBOUND_ROUTES_UNAVAILABLE_EVENT = "API app or event producer unavailable; inbound endpoints are not installed"
_DUPLICATE_RUNTIME_CONSUMER_NAMES_ERROR = "runtime and platform event consumers must have unique names"
_DISCORD_VOICE_ADAPTER_REQUIRED = "Discord runtime voice consumer has no active adapter capability"
_DISCORD_ADAPTER_KEY = "discord"
_RUNTIME_EVENT_PRODUCER_CONFIGURED_EVENT = "Internal runtime EventProducer configured"


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
        _event_redis_client: ScopedClients[Any] | None
        _event_platform_status: _EventPlatformStatus
        task_registry: TaskRegistry
        _event_consumer_tasks: tuple[SupervisedTask, ...]
        _relay_delivery_task: SupervisedTask | None
        _platform_consumer_runtime: ConsumerRuntime | None
        _runtime_consumer_runtime: ConsumerRuntime | None
        _relay_delivery_processor: EventProcessor[Any] | None
        _task_schedule_clock_task: SupervisedTask | None
        _assessment_announcer_task: SupervisedTask | None
        _source_reader_task: SupervisedTask | None
        _hook_dispatcher: HookDispatcher | None
        cache: DaemonCache

        def _log_background_task_exception(self, task_name: str) -> Callable[[asyncio.Task[object]], None]: ...

        async def _handle_session_closed(self, session_id: str) -> None: ...

        async def _recover_session_housekeeping(self) -> None: ...

        async def _handle_error(self, context: ErrorEventContext) -> None: ...

    async def _init_event_db_storage(self) -> None:
        """Initialize event storage."""
        self._event_db = await get_event_db()
        logger.info("EventDB initialized")

    async def _open_event_redis_client(self) -> ScopedClients[Any]:
        """Open the event platform's owned clients of both scopes' Redis independently of adapter startup."""
        if not config.redis.cluster.url:
            raise RuntimeError(_REDIS_UNCONFIGURED_ERROR)
        if not local_redis_configured():
            logger.warning(_LOCAL_REDIS_UNCONFIGURED_EVENT, computer=config.computer.name)
        if self._event_redis_client is not None:
            clients = self._event_redis_client
            try:
                await _ping_both(clients)
            except Exception:
                await _close_both(clients)
                self._event_redis_client = None
                raise
            return clients
        clients = scoped_redis_clients()
        try:
            await _ping_both(clients)
        except Exception:
            await _close_both(clients)
            raise
        self._event_redis_client = clients
        return clients

    async def _close_event_platform_redis(self) -> None:
        """Close the event platform's owned Redis pools after every consumer has settled."""
        clients = self._event_redis_client
        self._event_redis_client = None
        if clients is not None:
            await _close_both(clients)

    def _live_capability_map(self) -> FleetCapabilityMap | None:
        """The daemon's current fleet capability map; none until the cluster bridge is attached."""
        provider = self._fleet_capability_map_provider
        return provider() if provider is not None else None

    def _configure_event_producer(self, redis_clients: ScopedClients[Any]) -> EventProducer:
        """Build and register the event producer."""

        resolver = EnvelopeFactResolver(session_id=lambda: None, ownership_index=load_project_ownership_index)
        event_producer = EventProducer(
            redis_clients=redis_clients,
            fact_resolver=resolver,
            contraction_answer=contraction_answer_from_live_map(self._live_capability_map),
        )
        runtime_event_producer = EventProducer(
            redis_clients=redis_clients,
            fact_resolver=resolver,
            contraction_answer=contraction_answer_from_live_map(self._live_capability_map),
            stream=INTERNAL_EVENT_STREAM,
        )
        configure_producer(event_producer)
        configure_producer(runtime_event_producer)
        logger.info(_RUNTIME_EVENT_PRODUCER_CONFIGURED_EVENT, stream=INTERNAL_EVENT_STREAM)
        logger.info("EventProducer configured")
        return event_producer

    def _event_consumers(self) -> list[Consumer]:
        """The platform's own reactions to events, each an independent consumer on this computer."""
        assert self._event_db is not None  # initialized by _start_event_platform_prepare
        assert self._event_producer is not None  # configured by _start_event_platform_prepare
        assert self._event_catalog is not None  # built by _start_event_platform_prepare
        return [
            build_lifecycle_router_consumer(registered_project_paths),
            build_mirror_closure_consumer(),
            build_memory_closure_consumer(),
            build_procedure_activation_consumer(),
            build_event_bound_maintenance_consumer(),
            build_installation_reaction_consumer(self._event_producer),
            build_ci_run_outcomes_consumer(self._event_producer),
            build_failed_check_bugs_consumer(),
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

    async def _prepare_event_consumer_runtimes(self, redis_clients: ScopedClients[Any]) -> None:
        """Build and prepare both source sets without allowing a handler to execute."""
        assert self._event_db is not None  # initialized by _start_event_platform_prepare
        platform_consumers = self._event_consumers()
        runtime_consumers = build_runtime_event_consumers(
            lifecycle=self.lifecycle,
            client=self.client,
            close_housekeeping=self._handle_session_closed,
            recover_housekeeping=self._recover_session_housekeeping,
            report_error=self._handle_error,
            discord_voice_status=self._handle_discord_runtime_status,
            recover_discord_voice=self._recover_discord_runtime_status,
            compatibility_ingress=self._handle_internal_compat_ingress,
        )
        names = [consumer.name for consumer in (*platform_consumers, *runtime_consumers)]
        if len(names) != len(set(names)):
            raise ValueError(_DUPLICATE_RUNTIME_CONSUMER_NAMES_ERROR)
        await prepare_internal_event_handover(
            redis_clients.cluster,
            stream=INTERNAL_RUNTIME_EVENT_STREAM,
            computer=config.computer.name,
            consumers=[consumer for consumer in runtime_consumers if consumer.delivery is ConsumerDelivery.RETAINED],
            event_db=self._event_db,
        )
        platform_runtime = ConsumerRuntime(
            platform_consumers,
            redis_clients=redis_clients,
            db=self._event_db,
            computer=config.computer.name,
        )
        runtime_runtime = ConsumerRuntime(
            runtime_consumers,
            redis_clients=redis_clients,
            db=self._event_db,
            computer=config.computer.name,
            stream=INTERNAL_RUNTIME_EVENT_STREAM,
            codec=internal_event_entry_codec(),
        )
        await platform_runtime.prepare_group_positions()
        await runtime_runtime.prepare_group_positions()
        self._platform_consumer_runtime = platform_runtime
        self._runtime_consumer_runtime = runtime_runtime
        logger.info(
            "event_consumer_positions_prepared",
            consumers=[consumer.name for consumer in (*platform_consumers, *runtime_consumers)],
        )

    def _start_event_consumers_runtime(self) -> None:
        """Execute the prepared source sets after their request surface and adapters are bound."""
        platform_runtime = self._platform_consumer_runtime
        runtime_runtime = self._runtime_consumer_runtime
        if platform_runtime is None or runtime_runtime is None:
            raise RuntimeError("Event consumer positions must be prepared before execution")
        self._event_consumer_tasks = (
            *platform_runtime.supervise(self.task_registry, self.shutdown_event),
            *runtime_runtime.supervise(self.task_registry, self.shutdown_event),
        )
        logger.info(_EVENT_CONSUMERS_STARTED_EVENT)

    async def _recover_discord_runtime_status(self) -> None:
        """Recover voice focus through Discord's owner-local source query."""
        adapter = self.client.adapters.get(_DISCORD_ADAPTER_KEY)
        if adapter is None:
            if config.discord.token:
                raise RuntimeError(_DISCORD_VOICE_ADAPTER_REQUIRED)
            return
        await cast(RuntimeVoiceSurface, adapter).recover_runtime_voice_focus()

    async def _handle_discord_runtime_status(self, data: RuntimeSessionStatusData) -> None:
        """Deliver a live accepted-input identity without waiting for peer cache replication."""
        adapter = self.client.adapters.get(_DISCORD_ADAPTER_KEY)
        if adapter is not None:
            await cast(RuntimeVoiceSurface, adapter).handle_runtime_session_status(data)

    async def _handle_internal_compat_ingress(
        self,
        data: InternalEventCompatIngressData,
        event: ReceivedEvent,
    ) -> None:
        """Hand retained command carriers to their runtime owner; interrupted handling may be replayed."""
        context = decode_compat_ingress_context(data)
        if data.event_name == "agent_event" and isinstance(context, AgentEventContext):
            if event.source != config.computer.name:
                return
            handler = self.client.agent_event_handler
            if handler is None:
                raise RuntimeError("Retained agent event has no runtime coordinator capability")
            await handler(context)
            return
        if data.event_name == "session_close_requested" and isinstance(context, SessionLifecycleContext):
            if await db.get_session(context.session_id) is None:
                return
            command = CloseSessionCommand(
                session_id=context.session_id,
                request_id=occurrence_id(data.occurrence_id, "legacy-session-close", context.session_id),
            )
            await run_local_command(command)
            return
        if data.event_name == "system_command" and isinstance(context, SystemCommandContext):
            if event.source == config.computer.name:
                await self.client.dispatch_system_command(context)
            return
        logger.debug("No active reaction for retained internal event", event_name=data.event_name, event_id=event.id)

    async def _prepare_relay_delivery_consumer(self, dispatcher: HookDispatcher) -> None:
        """Prepare the relay reader position before any ingress can publish to its stream."""
        clients = self._event_redis_client
        if clients is None:
            raise RuntimeError("Relay delivery reader requires the event platform Redis connection")
        # Relayed events are cluster events: they enter on the ingress computer for every computer's reader.
        redis_client = clients.cluster
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
        await processor.prepare_group_position()
        self._relay_delivery_processor = processor

    def _start_relay_delivery_consumer(self) -> None:
        """Start the prepared relay reader after the API request surface is bound."""
        processor = self._relay_delivery_processor
        if processor is None:
            return
        self._relay_delivery_task = self.task_registry.supervise(
            _RELAY_DELIVERY_TASK_NAME, partial(processor.start, self.shutdown_event), restart=True
        )
        logger.info(_RELAY_DELIVERY_STARTED_EVENT, computer=config.computer.name)

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
        clock = TaskScheduleClock(event_producer)
        self._task_schedule_clock_task = self.task_registry.supervise(
            _TASK_SCHEDULE_CLOCK_TASK_NAME, partial(clock.run, self.shutdown_event), restart=True
        )
        logger.info("Task schedule minute clock started")

    def _start_assessment_announcer(self, event_producer: EventProducer) -> None:
        """Start the announcer that repeats the owed installation assessment while an install is owed."""
        announcer = AssessmentAnnouncer(event_producer, InstallationLayout(), config.computer.name)
        self._assessment_announcer_task = self.task_registry.supervise(
            _ASSESSMENT_ANNOUNCER_TASK_NAME, partial(announcer.run, self.shutdown_event), restart=True
        )
        logger.info(_ASSESSMENT_ANNOUNCER_STARTED_EVENT)

    def _start_installation_source_reader(self, event_producer: EventProducer) -> None:
        """Start the interval read of the followed source that feeds the channel decision beside the relayed signals."""
        reader = InstallationSourceReader(event_producer, InstallationLayout())
        self._source_reader_task = self.task_registry.supervise(
            _SOURCE_READER_TASK_NAME, partial(reader.run, self.shutdown_event), restart=True
        )
        logger.info(_SOURCE_READER_STARTED_EVENT)

    async def _start_event_platform_prepare(self) -> None:
        """Prepare the owned producer, both reader positions, and ingress boundary before startup producers run."""
        redis_configured = bool(config.redis.cluster.url)
        self._event_platform_status = _EventPlatformStatus(redis_configured=redis_configured)
        await self._init_event_db_storage()
        event_catalog = build_default_catalog()
        self._event_platform_status.pending_recovery_progress = "reader_positions_preparing"
        redis_clients = await self._open_event_redis_client()
        self._event_platform_status.redis_reachable = True
        event_producer = self._configure_event_producer(redis_clients)
        self._event_catalog = event_catalog
        self._event_producer = event_producer
        await self._prepare_event_consumer_runtimes(redis_clients)
        try:
            await self._init_webhook_service()
        except Exception:
            self._hook_dispatcher = None
            self._relay_delivery_processor = None
            logger.error("Webhook service initialization failed, continuing without webhooks", exc_info=True)
        self._event_platform_status.pending_recovery_progress = "reader_positions_prepared"

    async def _end_for_memory_transition(self, session_id: str) -> bool:
        """End a pre-transition conversation-memory worker through agent runtime's termination flow."""
        return await terminate_session(session_id, self.client, reason=_MEMORY_TRANSITION_END_REASON)

    async def _run_conversation_memory_transition(self) -> None:
        """Run the one-time worker transition before any consumer can release an extraction.

        A pass that cannot finish (a worker that would not end) is retried in the background until the transition
        is recorded, and nothing is released until then.
        """
        try:
            complete = await run_transition(self._end_for_memory_transition)
        except Exception:
            logger.error(_MEMORY_TRANSITION_PASS_FAILED_EVENT, exc_info=True)
            complete = False
        if complete:
            return
        logger.warning(_MEMORY_TRANSITION_INCOMPLETE_EVENT)
        task = asyncio.create_task(
            run_transition_until_complete(self._end_for_memory_transition, self.shutdown_event),
            name=_MEMORY_TRANSITION_TASK_NAME,
        )
        task.add_done_callback(self._log_background_task_exception(_MEMORY_TRANSITION_LOG_TASK_NAME))

    async def _start_event_consumers(self) -> None:
        """Start the event platform's consumer tasks after the API socket is bound."""
        clients = self._event_redis_client
        event_producer = self._event_producer
        assert event_producer is not None  # built by _start_event_platform_prepare
        assert clients is not None  # opened by _start_event_platform_prepare
        # The retired pipeline's group is on the cluster Redis.
        await self._destroy_retired_system_group(clients.cluster)
        computer_label = config.computer.name
        await self._run_conversation_memory_transition()
        self._start_event_consumers_runtime()
        self._start_relay_delivery_consumer()
        self._event_platform_status.pending_recovery_progress = "processor_started"
        logger.info(
            "event_platform_redis_available: pending recovery scheduled",
            redis_configured=self._event_platform_status.redis_configured,
            redis_reachable=True,
            pending_recovery_progress=self._event_platform_status.pending_recovery_progress,
        )
        await self._emit_daemon_restarted_event(event_producer, computer_label)
        self._start_task_schedule_clock(event_producer)
        self._start_assessment_announcer(event_producer)
        self._start_installation_source_reader(event_producer)

    async def _init_webhook_service(self) -> None:
        """Prepare the hook dispatcher, inbound routes and its reader position before startup producers run."""

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

        # Built-in routing of a configured person's GitHub comments to the session holding the item's claim.
        handler_registry.register(_GITHUB_COMMENT_HANDLER, handle_github_event)
        contract_registry.register(
            Contract(
                id=_GITHUB_COMMENT_CONTRACT,
                target=Target(handler=_GITHUB_COMMENT_HANDLER),
                source_criterion=PropertyCriterion(match=GITHUB_SOURCE),
                type_criterion=PropertyCriterion(match=[event_type.value for event_type in GitHubCommentEvent]),
            )
        )

        await self._prepare_relay_delivery_consumer(dispatcher)
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
