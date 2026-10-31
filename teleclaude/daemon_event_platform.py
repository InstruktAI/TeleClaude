"""Event platform and webhook service mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
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
from teleclaude.events.redis_reachability import RedisReachability, configure_reachability
from teleclaude.events.references import ComputerRef
from teleclaude.events.schemas.system import DaemonRestarted, DaemonRestartedData, RuntimeSessionStatusData
from teleclaude.events.scope import ScopedClients, scope_of
from teleclaude.events.scoped_redis import close_scoped_clients, local_redis_configured, scoped_redis_clients
from teleclaude.events.wire import PLATFORM_ENTRY_CODEC, LegacyFacts
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.github_handler import GitHubCommentEvent, handle_github_event
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.inbound import install_inbound_routes
from teleclaude.hooks.normalizers.github import GITHUB_SOURCE
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.relay_delivery import RelayDeliveryPipeline, relay_delivery_group
from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event
from teleclaude.install.ingress_receiver import receiver_units_installed
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


async def _close_both(clients: ScopedClients[Any]) -> None:
    """Close each scope's client and its owned pool."""
    await close_scoped_clients(clients)


_EVENT_DB_REQUIRED_FOR_PIPELINE_CONTEXT = "_build_pipeline_context always runs after _init_event_db_storage"
_RELAY_DELIVERY_PROCESSOR_NAME = "relay-delivery"
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
_DUPLICATE_RUNTIME_CONSUMER_NAMES_ERROR = "runtime and platform event consumers must have unique names"
_DISCORD_VOICE_ADAPTER_REQUIRED = "Discord runtime voice consumer has no active adapter capability"
_DISCORD_ADAPTER_KEY = "discord"
_RUNTIME_EVENT_PRODUCER_CONFIGURED_EVENT = "Internal runtime EventProducer configured"
_EVENT_PLATFORM_ATTACH_TASK_NAME = "event-platform-attach"
_EVENT_PLATFORM_ATTACH_FAILED_EVENT = "event_platform_attach_failed"
_EVENT_PLATFORM_ATTACH_END_REASON = "event-platform-attach-failed"
_EVENT_PLATFORM_ATTACH_STALLED_ERROR = "Event platform steps remain while every event Redis answers"
_EVENT_PLATFORM_DEGRADED_EVENT = "event_platform_redis_unreachable: startup continues degraded"


class _RecoveryProgress(StrEnum):
    """How far the event platform's reader recovery has come."""

    NOT_STARTED = "not_started"
    POSITIONS_PREPARING = "reader_positions_preparing"
    POSITIONS_PREPARED = "reader_positions_prepared"
    BLOCKED_REDIS_UNREACHABLE = "blocked_redis_unreachable"
    PROCESSOR_STARTED = "processor_started"


@dataclass
class _EventPlatformStatus:
    redis_configured: bool
    redis_reachable: bool | None = None
    pending_recovery_progress: _RecoveryProgress = _RecoveryProgress.NOT_STARTED


@dataclass
class _EventPlatformSteps:
    """The startup steps that need a Redis; each is done once, as soon as its Redis answers."""

    handover_consumers: list[Consumer] = field(default_factory=list[Consumer])
    handover_prepared: bool = False
    retired_group_destroyed: bool = False
    restarted_published: bool = False


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
        _event_reachability: RedisReachability | None
        _event_platform_status: _EventPlatformStatus
        _event_platform_steps: _EventPlatformSteps
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

        def request_shutdown(self, reason: str) -> None: ...

    async def _init_event_db_storage(self) -> None:
        """Initialize event storage."""
        self._event_db = await get_event_db()
        logger.info("EventDB initialized")

    async def _open_event_redis_client(self) -> ScopedClients[Any]:
        """Open the event platform's owned clients of both scopes' Redis independently of adapter startup.

        A Redis that does not answer within the probe deadline is recorded as unreachable and startup continues; a
        rejected credential still ends startup.
        """
        if not config.redis.cluster.url:
            raise RuntimeError(_REDIS_UNCONFIGURED_ERROR)
        if not local_redis_configured():
            logger.warning(_LOCAL_REDIS_UNCONFIGURED_EVENT, computer=config.computer.name)
        previous = self._event_reachability
        if previous is not None:
            await previous.aclose()
        clients = self._event_redis_client or scoped_redis_clients()
        reachability = RedisReachability(clients, self.shutdown_event)
        try:
            await reachability.probe()
        except Exception:
            await reachability.aclose()
            await _close_both(clients)
            self._event_redis_client = None
            self._event_reachability = None
            raise
        self._event_redis_client = clients
        self._event_reachability = reachability
        configure_reachability(reachability)
        return clients

    async def _close_event_platform_redis(self) -> None:
        """Close the event platform's owned Redis pools after every consumer has settled."""
        reachability = self._event_reachability
        self._event_reachability = None
        if reachability is not None:
            await reachability.aclose()
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

    def _reachability(self) -> RedisReachability:
        reachability = self._event_reachability
        assert reachability is not None  # opened by _start_event_platform_prepare
        return reachability

    def _cluster_answers(self) -> bool:
        clients = self._event_redis_client
        assert clients is not None  # opened by _start_event_platform_prepare
        return any(clients.cluster is answering for answering in self._reachability().answering_clients())

    async def _prepare_event_consumer_runtimes(self, redis_clients: ScopedClients[Any]) -> None:
        """Build both source sets and prepare the positions whose Redis answers, without allowing a handler to execute."""
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
        self._event_platform_steps.handover_consumers = [
            consumer for consumer in runtime_consumers if consumer.delivery is ConsumerDelivery.RETAINED
        ]
        self._platform_consumer_runtime = ConsumerRuntime(
            platform_consumers,
            redis_clients=redis_clients,
            reachability=self._reachability(),
            db=self._event_db,
            computer=config.computer.name,
        )
        self._runtime_consumer_runtime = ConsumerRuntime(
            runtime_consumers,
            redis_clients=redis_clients,
            reachability=self._reachability(),
            db=self._event_db,
            computer=config.computer.name,
            stream=INTERNAL_RUNTIME_EVENT_STREAM,
            codec=internal_event_entry_codec(),
        )
        await self._prepare_internal_handover()
        await self._prepare_consumer_positions()
        logger.info(
            "event_consumer_positions_prepared",
            consumers=[consumer.name for consumer in (*platform_consumers, *runtime_consumers)],
            awaiting_redis=[scope.value for scope in self._reachability().unanswering_scopes()],
        )

    async def _prepare_internal_handover(self) -> None:
        """Hand the retained runtime consumers' cluster groups over to their local readers, once the cluster answers."""
        steps = self._event_platform_steps
        clients = self._event_redis_client
        assert clients is not None  # opened by _start_event_platform_prepare
        assert self._event_db is not None  # initialized by _start_event_platform_prepare
        if steps.handover_prepared or not self._cluster_answers():
            return
        steps.handover_prepared = await self._reachability().attempt(
            (clients.cluster,),
            partial(
                prepare_internal_event_handover,
                clients.cluster,
                stream=INTERNAL_RUNTIME_EVENT_STREAM,
                computer=config.computer.name,
                consumers=steps.handover_consumers,
                event_db=self._event_db,
            ),
        )

    async def _prepare_consumer_positions(self) -> None:
        """Take the positions of the readers whose Redis answers now; the others wait for a later attach."""
        for runtime in (self._platform_consumer_runtime, self._runtime_consumer_runtime):
            if runtime is not None:
                await runtime.prepare_group_positions(self._reachability().answering_clients())

    async def _destroy_retired_group_when_cluster_answers(self) -> None:
        steps = self._event_platform_steps
        clients = self._event_redis_client
        assert clients is not None  # opened by _start_event_platform_prepare
        if steps.retired_group_destroyed or not self._cluster_answers():
            return
        # The retired pipeline's group is on the cluster Redis.
        steps.retired_group_destroyed = await self._reachability().attempt(
            (clients.cluster,), partial(self._destroy_retired_system_group, clients.cluster)
        )

    def _supervise_prepared_event_readers(self) -> None:
        """Execute the prepared readers whose Redis answers after their request surface and adapters are bound."""
        platform_runtime = self._platform_consumer_runtime
        runtime_runtime = self._runtime_consumer_runtime
        if platform_runtime is None or runtime_runtime is None:
            raise RuntimeError("Event consumer positions must be prepared before execution")
        answering = self._reachability().answering_clients()
        started = (
            *platform_runtime.supervise(self.task_registry, self.shutdown_event, answering),
            *runtime_runtime.supervise(self.task_registry, self.shutdown_event, answering),
        )
        self._event_consumer_tasks = (*self._event_consumer_tasks, *started)
        if started:
            logger.info(_EVENT_CONSUMERS_STARTED_EVENT, readers=len(started))
        if self._relay_delivery_processor is not None and self._relay_delivery_task is None and self._cluster_answers():
            self._start_relay_delivery_consumer()

    async def _publish_daemon_restarted_when_its_redis_answers(self) -> None:
        steps = self._event_platform_steps
        clients = self._event_redis_client
        event_producer = self._event_producer
        assert clients is not None  # opened by _start_event_platform_prepare
        assert event_producer is not None  # built by _start_event_platform_prepare
        client = clients.for_scope(scope_of(DaemonRestarted.type_name()))
        if steps.restarted_published or not any(
            client is answering for answering in self._reachability().answering_clients()
        ):
            return
        steps.restarted_published = await self._reachability().attempt(
            (client,), partial(self._emit_daemon_restarted_event, event_producer, config.computer.name)
        )

    def _event_platform_steps_remaining(self) -> bool:
        """Whether a step that needs a Redis is still undone."""
        steps = self._event_platform_steps
        runtimes = (self._platform_consumer_runtime, self._runtime_consumer_runtime)
        relay_owed = self._hook_dispatcher is not None and (
            self._relay_delivery_processor is None or self._relay_delivery_task is None
        )
        return (
            not (steps.handover_prepared and steps.retired_group_destroyed and steps.restarted_published)
            or any(runtime is not None and runtime.unattached() for runtime in runtimes)
            or relay_owed
        )

    async def _advance_event_platform_steps(self) -> None:
        """Do every undone step the answering Redis now allow, in startup order."""
        await self._prepare_internal_handover()
        await self._destroy_retired_group_when_cluster_answers()
        await self._attach_relay_position()
        await self._prepare_consumer_positions()
        self._supervise_prepared_event_readers()
        await self._publish_daemon_restarted_when_its_redis_answers()

    async def _attach_event_platform(self) -> None:
        """Complete the startup steps a Redis that did not answer held back, as each Redis answers.

        A Redis that stops answering again returns the task to waiting; any other failure requests the daemon's
        ordinary shutdown, as the same failure does in a start where every Redis answers.
        """
        try:
            advanced_without_waiting = False
            while self._event_platform_steps_remaining():
                waiting = self._reachability().unanswering_clients()
                if waiting:
                    if not await self._reachability().until_any_answers(waiting):
                        return
                    advanced_without_waiting = False
                elif advanced_without_waiting:
                    # A pass that found every Redis answering left steps undone: nothing is left to wait for.
                    raise RuntimeError(_EVENT_PLATFORM_ATTACH_STALLED_ERROR)
                else:
                    # A Redis that answered again before this task began holds nothing back; its steps are due now.
                    advanced_without_waiting = True
                await self._advance_event_platform_steps()
        except Exception:
            logger.error(_EVENT_PLATFORM_ATTACH_FAILED_EVENT, exc_info=True)
            self.request_shutdown(_EVENT_PLATFORM_ATTACH_END_REASON)
            return
        self._note_event_platform_attached()

    def _note_event_platform_attached(self) -> None:
        self._event_platform_status.redis_reachable = True
        self._event_platform_status.pending_recovery_progress = _RecoveryProgress.PROCESSOR_STARTED
        logger.info(
            "event_platform_redis_available: pending recovery scheduled",
            redis_configured=self._event_platform_status.redis_configured,
            redis_reachable=True,
            pending_recovery_progress=self._event_platform_status.pending_recovery_progress,
        )

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

    async def _attach_relay_position(self) -> None:
        """Prepare the relay reader's position once the cluster Redis answers; a no-op when done or without webhooks."""
        dispatcher = self._hook_dispatcher
        clients = self._event_redis_client
        if dispatcher is None or clients is None or self._relay_delivery_processor is not None:
            return
        if not self._cluster_answers():
            return
        await self._reachability().attempt(
            (clients.cluster,), partial(self._prepare_relay_delivery_consumer, dispatcher)
        )

    async def _prepare_relay_delivery_consumer(self, dispatcher: HookDispatcher) -> None:
        """Prepare this computer's relay reader position on the cluster event stream."""
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
            group=relay_delivery_group(computer_label),
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
        """Prepare the owned producer and the reader positions whose Redis answers before startup producers run.

        A Redis that does not answer neither stops startup nor holds it: its readers are attached when it answers.
        """
        redis_configured = bool(config.redis.cluster.url)
        self._event_platform_status = _EventPlatformStatus(redis_configured=redis_configured)
        self._event_platform_steps = _EventPlatformSteps()
        await self._init_event_db_storage()
        event_catalog = build_default_catalog()
        self._event_platform_status.pending_recovery_progress = _RecoveryProgress.POSITIONS_PREPARING
        redis_clients = await self._open_event_redis_client()
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
        unanswering = self._reachability().unanswering_scopes()
        if unanswering:
            self._event_platform_status.redis_reachable = False
            self._event_platform_status.pending_recovery_progress = _RecoveryProgress.BLOCKED_REDIS_UNREACHABLE
            logger.warning(
                _EVENT_PLATFORM_DEGRADED_EVENT,
                scopes=[scope.value for scope in unanswering],
                redis_configured=redis_configured,
            )
            return
        self._event_platform_status.redis_reachable = True
        self._event_platform_status.pending_recovery_progress = _RecoveryProgress.POSITIONS_PREPARED

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
        """Start the event platform's consumer tasks after the API socket is bound.

        Readers whose Redis does not answer are attached by one tracked task as that Redis answers.
        """
        assert self._event_producer is not None  # built by _start_event_platform_prepare
        event_producer = self._event_producer
        self._event_consumer_tasks = ()
        await self._destroy_retired_group_when_cluster_answers()
        await self._run_conversation_memory_transition()
        self._supervise_prepared_event_readers()
        await self._publish_daemon_restarted_when_its_redis_answers()
        self._start_task_schedule_clock(event_producer)
        self._start_assessment_announcer(event_producer)
        self._start_installation_source_reader(event_producer)
        if self._event_platform_steps_remaining():
            self.task_registry.spawn(self._attach_event_platform(), name=_EVENT_PLATFORM_ATTACH_TASK_NAME)
            return
        self._note_event_platform_attached()

    async def _init_webhook_service(self) -> None:
        """Prepare the hook dispatcher and its relay reader position before startup producers run."""

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

        await self._attach_relay_position()
        self._install_inbound_routes()

        logger.info("Webhook service initialized")

    def _install_inbound_routes(self) -> None:
        """Mount the inbound endpoints on the API app while the daemon serves this computer's ingress."""
        if not config.computer.is_ingress_node or receiver_units_installed():
            return
        app = getattr(getattr(self.lifecycle, "api_server", None), "app", None)
        producer = self._event_producer
        if app is None or producer is None:
            logger.warning("inbound_routes_unavailable")
            return
        install_inbound_routes(app, producer)
        logger.info("inbound_routes_installed")
