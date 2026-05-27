"""Event platform and webhook service mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.channels.worker import run_subscription_worker
from teleclaude.config import config
from teleclaude.config.loader import load_project_config
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.db import get_db
from teleclaude.core.event_bus import RedisStreamsClient, configure_event_bus, event_bus
from teleclaude.deployment.handler import (
    DEPLOYMENT_FANOUT_CHANNEL,
    configure_deployment_handler,
    handle_deployment_event,
)
from teleclaude.events import (
    EventDB,
    EventLevel,
    EventProcessor,
    EventProducer,
    EventVisibility,
    Pipeline,
    PipelineContext,
    build_default_catalog,
    configure_producer,
    get_event_db,
)
from teleclaude.events.cartridges import (
    ClassificationCartridge,
    CorrelationCartridge,
    DeduplicationCartridge,
    EnrichmentCartridge,
    IntegrationTriggerCartridge,
    LifecycleRouterCartridge,
    NotificationProjectorCartridge,
    TrustCartridge,
)
from teleclaude.events.cartridges.correlation import CorrelationConfig
from teleclaude.events.cartridges.trust import TrustConfig
from teleclaude.events.delivery.telegram import TelegramDeliveryAdapter
from teleclaude.events.envelope import EventEnvelope as EventsEnvelope
from teleclaude.hooks.api_routes import set_contract_registry
from teleclaude.hooks.bridge import EventBusBridge
from teleclaude.hooks.config import load_hooks_config
from teleclaude.hooks.delivery import WebhookDeliveryWorker
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.handlers import HandlerRegistry
from teleclaude.hooks.inbound import InboundEndpointRegistry, NormalizerRegistry
from teleclaude.hooks.normalizers import register_builtin_normalizers
from teleclaude.hooks.registry import ContractRegistry
from teleclaude.hooks.webhook_models import Contract, PropertyCriterion, Target
from teleclaude.hooks.whatsapp_handler import handle_whatsapp_event
from teleclaude.paths import PEOPLE_DIR
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.config.schema import PersonConfig
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.lifecycle import DaemonLifecycle

logger = get_logger(__name__)


def daemon_project_config_path() -> Path:
    """Path to the daemon's own (mother) project ``teleclaude.yml``.

    It lives at the daemon's working dir — NOT next to the global runtime
    ``config.yml`` in ``~/.teleclaude`` (that dir holds the GLOBAL teleclaude.yml
    with people/event_domains, which is not a ProjectConfig).
    """
    return Path(config.computer.default_working_dir) / "teleclaude.yml"


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
        _event_pipeline: Pipeline | None
        _event_platform_status: _EventPlatformStatus
        _signal_ai_client: object | None
        _deployment_fanout_task: asyncio.Task[object] | None
        _contract_sweep_task: asyncio.Task[object] | None
        _event_processor_task: asyncio.Task[object] | None
        _internal_event_bus_task: asyncio.Task[object] | None
        _ingest_scheduler_task: asyncio.Task[object] | None
        webhook_delivery_task: asyncio.Task[object] | None
        channel_subscription_worker_task: asyncio.Task[object] | None

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

    def _configure_event_producer(self, redis_client: object) -> EventProducer:
        """Build and register the event producer."""
        event_producer = EventProducer(redis_client=redis_client)
        configure_producer(event_producer)
        logger.info("EventProducer configured")
        return event_producer

    def _iter_admin_people_configs(self) -> list[tuple[str, PersonConfig]]:
        """Load admin person configs from the global people directory."""
        from teleclaude.config.loader import load_global_config, load_person_config  # startup boundary

        people_dir = PEOPLE_DIR
        global_cfg = load_global_config()
        admin_configs: list[tuple[str, PersonConfig]] = []
        for person in global_cfg.people:
            if person.role != HUMAN_ROLE_ADMIN:
                continue
            person_key = person.name.lower().replace(" ", "_")
            person_cfg_path = people_dir / person_key / "teleclaude.yml"
            if not person_cfg_path.exists():
                continue
            try:
                person_cfg = load_person_config(person_cfg_path)
            except Exception:
                continue
            admin_configs.append((person.name, person_cfg))
        return admin_configs

    def _build_push_callbacks(self) -> list[Callable[..., object]]:
        """Build notification push callbacks for event projections."""
        push_callbacks: list[Callable[..., object]] = []
        self._register_api_push_callback(push_callbacks)
        self._register_telegram_delivery_callbacks(push_callbacks)
        self._register_discord_delivery_callbacks(push_callbacks)
        self._register_whatsapp_delivery_callbacks(push_callbacks)
        return push_callbacks

    def _register_api_push_callback(self, push_callbacks: list[Callable[..., object]]) -> None:
        """Register websocket push if the API server is available."""
        api_server = getattr(self.lifecycle, "api_server", None)
        if api_server is None:
            return
        api_server._event_db = self._event_db
        push_callbacks.append(api_server._notification_push)

    def _register_telegram_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        """Register Telegram notification delivery for admins."""
        if not config.telegram:
            return

        from teleclaude.services.telegram import send_telegram_dm  # startup boundary

        try:
            for person_name, person_cfg in self._iter_admin_people_configs():
                chat_id = person_cfg.creds.telegram.chat_id if person_cfg.creds.telegram else None
                if not chat_id:
                    continue
                adapter = TelegramDeliveryAdapter(
                    chat_id=chat_id,
                    send_fn=send_telegram_dm,
                    shutdown_check=self.shutdown_event.is_set,
                )
                push_callbacks.append(adapter.on_notification)
                logger.info("TelegramDeliveryAdapter registered for admin %s", person_name)
        except Exception:
            logger.warning("Could not load people config for Telegram delivery adapter")

    def _register_discord_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        """Register Discord notification delivery for admins."""
        if not config.discord.enabled:
            return

        from teleclaude.events.delivery.discord import DiscordDeliveryAdapter  # startup boundary
        from teleclaude.services.discord import send_discord_dm  # startup boundary

        try:
            for person_name, person_cfg in self._iter_admin_people_configs():
                user_id = person_cfg.creds.discord.user_id if person_cfg.creds.discord else None
                if not user_id:
                    continue
                adapter = DiscordDeliveryAdapter(
                    user_id=user_id,
                    send_fn=send_discord_dm,
                    shutdown_check=self.shutdown_event.is_set,
                )
                push_callbacks.append(adapter.on_notification)
                logger.info("DiscordDeliveryAdapter registered for admin %s", person_name)
        except Exception:
            logger.warning("Could not load people config for Discord delivery adapter")

    def _register_whatsapp_delivery_callbacks(self, push_callbacks: list[Callable[..., object]]) -> None:
        """Register WhatsApp notification delivery for admins."""
        if not config.whatsapp.enabled:
            return

        from functools import partial  # startup boundary

        from teleclaude.events.delivery.whatsapp import WhatsAppDeliveryAdapter  # startup boundary
        from teleclaude.services.whatsapp import send_whatsapp_message  # startup boundary

        try:
            for person_name, person_cfg in self._iter_admin_people_configs():
                phone_number = person_cfg.creds.whatsapp.phone_number if person_cfg.creds.whatsapp else None
                if not phone_number:
                    continue
                bound_send_fn = partial(
                    send_whatsapp_message,
                    phone_number_id=config.whatsapp.phone_number_id,
                    access_token=config.whatsapp.access_token,
                    api_version=config.whatsapp.api_version,
                )
                adapter = WhatsAppDeliveryAdapter(
                    phone_number=phone_number,
                    send_fn=bound_send_fn,
                    shutdown_check=self.shutdown_event.is_set,
                )
                push_callbacks.append(adapter.on_notification)
                logger.info("WhatsAppDeliveryAdapter registered for admin %s", person_name)
        except Exception:
            logger.warning("Could not load people config for WhatsApp delivery adapter")

    def _build_integration_trigger(self) -> IntegrationTriggerCartridge:
        """Create the integration trigger cartridge."""
        from teleclaude.core.integration_bridge import spawn_integrator_session  # startup boundary

        return IntegrationTriggerCartridge(
            spawn_callback=spawn_integrator_session,
        )

    def _build_pipeline_context(
        self,
        event_catalog: object,
        push_callbacks: list[Callable[..., object]],
        event_producer: EventProducer,
    ) -> PipelineContext:
        """Create the shared pipeline context."""
        return PipelineContext(
            catalog=event_catalog,  # type: ignore[arg-type]
            db=self._event_db,
            push_callbacks=push_callbacks,
            trust_config=TrustConfig(
                known_sources=frozenset({"daemon", "prepare-worker", "review-worker", "correlation"})
            ),
            correlation_config=CorrelationConfig(),
            producer=event_producer,
        )

    def _build_domain_runner(self) -> object | None:
        """Build the optional domain runner."""
        event_domains_cfg = getattr(config, "event_domains", None)
        if event_domains_cfg is None:
            return None
        try:
            from teleclaude.events.startup import build_domain_pipeline_runner  # startup boundary

            domain_runner = build_domain_pipeline_runner(event_domains_cfg)
            logger.info("Domain pipeline runner built successfully")
            return domain_runner
        except Exception as domain_err:
            logger.error(
                "Failed to build domain pipeline runner: %s — domain pipeline disabled",
                domain_err,
            )
            return None

    def _build_pipeline(
        self,
        context: PipelineContext,
        integration_trigger: IntegrationTriggerCartridge,
    ) -> Pipeline:
        """Build the system event pipeline."""
        return Pipeline(
            [
                TrustCartridge(),
                integration_trigger,
                DeduplicationCartridge(),
                EnrichmentCartridge(),
                CorrelationCartridge(),
                ClassificationCartridge(),
                NotificationProjectorCartridge(),
                LifecycleRouterCartridge(),
            ],
            context,
            domain_runner=self._build_domain_runner(),  # type: ignore[arg-type]
        )

    def _start_event_processor(self, redis_client: object, pipeline: Pipeline) -> str:
        """Start the Redis-backed event processor."""
        computer_name = getattr(config, "computer", None)
        computer_label = getattr(computer_name, "name", "local") if computer_name else "local"
        reliability = config.event_reliability
        event_processor = EventProcessor(
            redis_client=redis_client,
            pipeline=pipeline,
            consumer_name=f"{computer_label}-{os.getpid()}",
            idle_threshold_ms=reliability.idle_threshold_ms,
            max_attempts=reliability.max_attempts,
            sweep_interval_ms=reliability.sweep_interval_ms,
            dlq_destination=reliability.dlq_destination,
        )
        self._event_processor_task = asyncio.create_task(
            event_processor.start(self.shutdown_event), name="event-processor"
        )
        self._event_processor_task.add_done_callback(self._log_background_task_exception("event_processor"))
        logger.info("EventProcessor started")
        return computer_label

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
            EventsEnvelope(
                event="system.daemon.restarted",
                source="daemon",
                level=EventLevel.INFRASTRUCTURE,
                domain="system",
                visibility=EventVisibility.CLUSTER,
                description=f"Daemon restarted on {computer_label}",
                payload={"computer": computer_label, "pid": os.getpid()},
            )
        )
        logger.info("Event 'system.daemon.restarted' emitted")

    def _configure_signal_context(
        self,
        context: PipelineContext,
        event_producer: EventProducer,
        signal_ai: object,
    ) -> None:
        """Attach signal AI integrations to the shared pipeline context."""
        context.ai_client = signal_ai
        context.emit = event_producer.emit

    def _start_signal_pipeline(
        self,
        pipeline: Pipeline,
        context: PipelineContext,
        event_producer: EventProducer,
    ) -> None:
        """Start the optional signal ingestion pipeline."""
        signal_cfg = getattr(config, "signal", None)
        if signal_cfg is None:
            return

        try:
            import anthropic  # startup boundary

            from teleclaude.events.cartridges.signal import (  # startup boundary
                SignalClusterCartridge,
                SignalIngestCartridge,
                SignalSynthesizeCartridge,
            )
            from teleclaude.events.cartridges.signal.synthesize import SynthesizeConfig  # startup boundary
            from teleclaude.events.signal.ai import DefaultSignalAIClient  # startup boundary
            from teleclaude.events.signal.clustering import ClusteringConfig  # startup boundary
            from teleclaude.events.signal.scheduler import IngestScheduler  # startup boundary
            from teleclaude.events.signal.sources import SignalSourceConfig  # startup boundary

            raw_ai = anthropic.AsyncAnthropic()
            signal_ai = DefaultSignalAIClient(raw_ai)
            self._signal_ai_client = raw_ai
            signal_db = self._event_db.signal
            source_config_data = signal_cfg if isinstance(signal_cfg, dict) else {}
            source_config = SignalSourceConfig(**source_config_data)

            self._configure_signal_context(context, event_producer, signal_ai)

            ingest_cartridge = SignalIngestCartridge(config=source_config, ai=signal_ai, signal_db=signal_db)
            cluster_cartridge = SignalClusterCartridge(
                config=ClusteringConfig(),
                ai=signal_ai,
                signal_db=signal_db,
            )
            synthesize_cartridge = SignalSynthesizeCartridge(
                config=SynthesizeConfig(),
                ai=signal_ai,
                signal_db=signal_db,
            )

            self._ingest_scheduler_task = asyncio.create_task(
                IngestScheduler(ingest_cartridge, context, source_config.pull_interval_seconds).run(
                    self.shutdown_event
                ),
                name="ingest-scheduler",
            )
            self._ingest_scheduler_task.add_done_callback(self._log_background_task_exception("ingest_scheduler"))
            pipeline.register(cluster_cartridge)
            pipeline.register(synthesize_cartridge)
            logger.info(
                "Signal pipeline started (%d sources, interval=%ds)",
                len(source_config.sources),
                source_config.pull_interval_seconds,
            )
        except ImportError:
            logger.warning(
                "Signal pipeline failed to start (missing optional dependency); signal ingestion disabled",
                exc_info=True,
            )
        except Exception:
            logger.error("Signal pipeline failed to start; signal ingestion disabled", exc_info=True)

    async def _start_event_platform(self) -> None:
        """Initialize and start the event processing platform.

        Redis is required. If it is unreachable, the daemon must not continue —
        downstream code (operations, integration, signals) emits events
        unconditionally and treating a missing producer as "degraded but
        running" hides real failures behind ERROR-log spam.
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
        push_callbacks = self._build_push_callbacks()
        integration_trigger = self._build_integration_trigger()
        context = self._build_pipeline_context(event_catalog, push_callbacks, event_producer)
        pipeline = self._build_pipeline(context, integration_trigger)
        self._event_pipeline = pipeline
        computer_label = self._start_event_processor(redis_client, pipeline)
        self._event_platform_status.pending_recovery_progress = "processor_started"
        logger.info(
            "event_platform_redis_available: pending recovery scheduled",
            redis_configured=redis_configured,
            redis_reachable=True,
            pending_recovery_progress=self._event_platform_status.pending_recovery_progress,
        )
        await self._emit_daemon_restarted_event(event_producer, computer_label)
        self._start_signal_pipeline(pipeline, context, event_producer)

    async def _init_webhook_service(self) -> None:
        """Initialize the webhook service subsystem (contracts, handlers, dispatcher, bridge, delivery)."""

        db = await get_db()
        contract_registry = ContractRegistry()
        handler_registry = HandlerRegistry()
        dispatcher = HookDispatcher(contract_registry, handler_registry, db.enqueue_webhook)  # type: ignore[arg-type]
        bridge = EventBusBridge(dispatcher)
        delivery_worker = WebhookDeliveryWorker()
        project_config = load_project_config(daemon_project_config_path())

        # Load contracts from DB
        await contract_registry.load_from_db()

        # Built-in inbound WhatsApp handling (global subscription handler).
        handler_registry.register("whatsapp_inbound", handle_whatsapp_event)
        await contract_registry.register(
            Contract(
                id="builtin-whatsapp-inbound",
                target=Target(handler="whatsapp_inbound"),
                source_criterion=PropertyCriterion(match="whatsapp"),
                type_criterion=PropertyCriterion(pattern="message.*"),
                source="programmatic",
            )
        )

        # Built-in deployment channel handler.
        redis_transport = self.client.transport
        _get_redis_fn = redis_transport._get_redis if isinstance(redis_transport, RedisTransport) else None
        configure_deployment_handler(_get_redis_fn)
        handler_registry.register("deployment_update", handle_deployment_event)
        await contract_registry.register(
            Contract(
                id="deployment-github",
                source_criterion=PropertyCriterion(match="github"),
                type_criterion=PropertyCriterion(match=["push", "release"]),
                target=Target(handler="deployment_update"),
                source="programmatic",
            )
        )
        await contract_registry.register(
            Contract(
                id="deployment-fanout",
                source_criterion=PropertyCriterion(match="deployment"),
                type_criterion=PropertyCriterion(match="version_available"),
                target=Target(handler="deployment_update"),
                source="programmatic",
            )
        )
        if isinstance(redis_transport, RedisTransport):
            self._deployment_fanout_task = asyncio.create_task(
                self._deployment_fanout_consumer(dispatcher, redis_transport),
                name="deployment-fanout",
            )
            self._deployment_fanout_task.add_done_callback(self._log_background_task_exception("deployment_fanout"))

        # Register built-in normalizers.
        normalizer_registry = NormalizerRegistry()
        register_builtin_normalizers(normalizer_registry)

        # Load config-driven contracts and inbound endpoints.
        # Contracts load regardless of API server availability; inbound routes require it.
        lifecycle_api_server = getattr(self.lifecycle, "api_server", None)
        app = getattr(lifecycle_api_server, "app", None)
        inbound_registry = None
        if app is not None:
            inbound_registry = InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)
        else:
            logger.warning("API server app unavailable; inbound webhooks will not be registered")
        await load_hooks_config(
            project_config.hooks.model_dump(),
            contract_registry,
            inbound_registry=inbound_registry,
        )

        if project_config.channel_subscriptions:
            redis_adapter = self.client.transport
            if isinstance(redis_adapter, RedisTransport):
                try:
                    redis_client = await redis_adapter._get_redis()
                except Exception as exc:
                    logger.error(
                        "Failed to start channel subscription worker due to redis error",
                        error=str(exc),
                        exc_info=True,
                    )
                else:
                    self.channel_subscription_worker_task = asyncio.create_task(
                        run_subscription_worker(
                            redis=redis_client,
                            subscriptions=project_config.channel_subscriptions,
                            shutdown_event=self.shutdown_event,
                        ),
                        name="channel-subscription-worker",
                    )
                    self.channel_subscription_worker_task.add_done_callback(
                        self._log_background_task_exception("subscription_worker")
                    )
            else:
                logger.warning("Redis adapter unavailable; skipping channel subscription worker")

        # Wire contract registry into API routes
        set_contract_registry(contract_registry)

        # Subscribe bridge to event bus
        bridge.register(event_bus)

        # Start delivery worker
        self.webhook_delivery_task = asyncio.create_task(
            delivery_worker.run(self.shutdown_event), name="webhook-delivery"
        )
        self.webhook_delivery_task.add_done_callback(self._log_background_task_exception("webhook_delivery"))
        self._webhook_delivery_worker = delivery_worker
        self._contract_registry = contract_registry

        # Start contract TTL sweep (every 60s)
        self._contract_sweep_task = asyncio.create_task(self._contract_sweep_loop(), name="contract-sweep")
        self._contract_sweep_task.add_done_callback(self._log_background_task_exception("contract_sweep"))

        logger.info("Webhook service initialized (%d contracts loaded)", len(contract_registry._cache))

    async def _deployment_fanout_consumer(self, dispatcher: HookDispatcher, redis_transport: RedisTransport) -> None:
        """Consume deployment version_available events from Redis Stream and dispatch locally.

        Messages published by this daemon carry a daemon_id matching config.computer.name.
        The consumer skips those to avoid double-executing updates that this daemon already
        triggered directly (github-source path calls execute_update before publishing).
        Remote daemons have different daemon_id values and will process the message normally.
        """
        from teleclaude.hooks.webhook_models import HookEvent as _HookEvent  # startup boundary

        last_id = "$"  # only new messages after startup
        logger.info("Deployment fanout consumer started (channel=%s)", DEPLOYMENT_FANOUT_CHANNEL)
        while not self.shutdown_event.is_set():
            try:
                redis = await redis_transport._get_redis()
                results = await redis.xread({DEPLOYMENT_FANOUT_CHANNEL: last_id}, count=10, block=5000)
                if not results:
                    continue
                for _stream, messages in results:
                    for msg_id, data in messages:
                        last_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                        event_json = data.get(b"event") or data.get("event")
                        if event_json is None:
                            continue
                        if isinstance(event_json, bytes):
                            event_json = event_json.decode()
                        try:
                            event = _HookEvent.from_json(event_json)
                            if event.properties.get("daemon_id") == config.computer.name:
                                logger.debug("Deployment fanout: skipping self-originated message")
                                continue
                            await dispatcher.dispatch(event)
                        except Exception as exc:
                            logger.warning("Deployment fanout: dispatch failed: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Deployment fanout consumer error: %s", exc)
                await asyncio.sleep(5)
        logger.info("Deployment fanout consumer stopped")

    async def _contract_sweep_loop(self) -> None:
        """Periodically deactivate expired contracts."""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(60)
                if hasattr(self, "_contract_registry") and self._contract_registry:
                    await self._contract_registry.sweep_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Contract sweep failed", exc_info=True)
