"""Centralized daemon lifecycle management."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord.message_ops import reconcile_pending_discord_send_intents
from teleclaude.api_server import APIServer, RequestSurface
from teleclaude.config.machine import config
from teleclaude.core.cleanup_step import cleanup_step
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_delivery import reconcile_outstanding_conversation_deliveries
from teleclaude.core.db import db
from teleclaude.core.degradation import DegradationRecord
from teleclaude.core.events import ProjectRefreshTrigger
from teleclaude.core.next_machine.worktree_home import reconcile_worktree_homes
from teleclaude.core.operations.service import OperationsService, get_operations_service, set_operations_service
from teleclaude.core.restart_budget import RestartBudget
from teleclaude.core.runtime_events import configure_session_source_reconciler
from teleclaude.core.session_cleanup import end_legacy_restricted_sessions
from teleclaude.core.session_config_subject import (
    backfill_session_config_subjects,
    backfill_session_subject_owners,
)
from teleclaude.core.session_materialization import SessionMaterializer
from teleclaude.core.store_opening import open_stores
from teleclaude.core.voice_recovery import recover_voice_transcriptions
from teleclaude.core.workflow_store.store import close_workflow_stores
from teleclaude.memory.store import MemoryStore
from teleclaude.runtime.agy_workspace_trust import remove_vanished_worktree_trust
from teleclaude.services.project_catalog import get_project_catalog_service

if TYPE_CHECKING:  # pragma: no cover
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.reminders import ReminderService
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry
from teleclaude.api_models import TodoDTO
from teleclaude.core import command_handlers
from teleclaude.core.inbound_queue import get_inbound_queue_manager

logger = get_logger(__name__)

_INBOUND_SHUTDOWN_COMPONENT = "inbound_queue"
_API_SHUTDOWN_COMPONENT = "api_server"
_REMINDER_SHUTDOWN_COMPONENT = "reminder_scheduler"
_STORAGE_SHUTDOWN_COMPONENT = "storage"
_TODOS_STORAGE_SHUTDOWN_COMPONENT = "todos_storage"

_CUTOVER_GENERATIONS_SEEDED_EVENT = "lifecycle_cutover_generations_seeded"
_DISCORD_SEND_INTENTS_RECONCILED_EVENT = "lifecycle_discord_send_intents_reconciled"

_WORKTREE_HOME_RECONCILE_TASK = "worktree-home-reconcile"
_FINAL_OUTPUT_RECONCILE_TASK = "final-output-reconcile"
_REMINDER_SCHEDULER_TASK = "reminder-scheduler"

_REQUEST_SURFACE_EXIT_CLEAN_EVENT = "Request surface exited cleanly; skipping restart"
_REQUEST_SURFACE_EXIT_EVENT = "Request surface exit detected; scheduling restart"
_API_RESTART_NO_LOOP_EVENT = "No running event loop to restart the request surface; requesting the daemon's shutdown"
_API_RESTART_EXHAUSTED_EVENT = "Request surface restart limit exhausted; requesting the daemon's shutdown"
_API_RESTART_FAILED_EVENT = "Request surface restart failed; scheduling another attempt"
_API_RESTART_UNAVAILABLE_EVENT = "Request surface not available; cannot restart"
_API_RESTART_ESCALATION_REASON = "request-surface-restart:{reason}"
_EXIT_REASON = "{surface}_{kind}"


class _ExitKind(StrEnum):
    """How a request-surface server came to exit."""

    CRASH = "crash"
    DONE = "done"


class DaemonLifecycle:
    """Own startup/shutdown ordering and API server restart policy."""

    def __init__(
        self,
        *,
        client: AdapterClient,
        cache: DaemonCache,
        shutdown_event: asyncio.Event,
        task_registry: TaskRegistry,
        reminder_service: ReminderService,
        degradations: DegradationRecord,
        runtime_settings: RuntimeSettings | None = None,
        log_background_task_exception: Callable[[str], Callable[[asyncio.Task[object]], None]],
        init_voice_handler: Callable[[], None],
        recover_session_startups: Callable[[], Awaitable[None]],
        event_platform_init: Callable[[], Awaitable[None]],
        event_consumer_start: Callable[[], Awaitable[None]],
        api_restart_max: int,
        api_restart_window_s: float,
        api_restart_backoff_s: float,
        escalate: Callable[[str], None],
    ) -> None:
        self.client = client
        self.cache = cache
        self.session_materializer = SessionMaterializer(db, cache, computer=config.computer.name)
        self.runtime_settings = runtime_settings
        self.shutdown_event = shutdown_event
        self.task_registry = task_registry
        self.reminder_service = reminder_service
        self.degradations = degradations
        self._log_background_task_exception = log_background_task_exception
        self._init_voice_handler = init_voice_handler
        self._recover_session_startups = recover_session_startups
        self._event_platform_init = event_platform_init
        self._event_consumer_start = event_consumer_start
        self._escalate = escalate

        self._api_restart_lock = asyncio.Lock()
        self._api_restart_budget = RestartBudget(
            max_restarts=api_restart_max,
            window_s=api_restart_window_s,
            backoff_s=api_restart_backoff_s,
        )
        self._started = False
        self._reminder_scheduler: SupervisedTask | None = None
        self.api_server: APIServer | None = None

    async def startup(self) -> None:
        """Start core components in a defined order."""
        if self._started:
            logger.warning("Lifecycle startup already completed; skipping")
            return
        startup_started_at = time.perf_counter()
        logger.info("[STARTUP] Opening stores (usually <1s)")
        await open_stores()
        configure_session_source_reconciler(self.session_materializer.reconcile)
        logger.info("Stores opened in %.3fs", time.perf_counter() - startup_started_at)

        # Build the current request surface before event consumers are composed.
        # The surface is not listening yet; the platform can prepare its producer
        # and reader positions without allowing a reaction to call an unbound API.
        self.api_server = APIServer(
            self.client,
            cache=self.cache,
            session_materializer=self.session_materializer,
            task_registry=self.task_registry,
            runtime_settings=self.runtime_settings,
            reminder_service=self.reminder_service,
            degradations=self.degradations,
            refresh_local_projects=self.refresh_local_projects,
        )

        event_platform_started_at = time.perf_counter()
        logger.info("[STARTUP] Preparing event platform and reader positions (usually <1s)")
        await self._event_platform_init()
        logger.info("Event platform prepared in %.3fs", time.perf_counter() - event_platform_started_at)

        # These startup writes can publish invalidations, so the producer and
        # every reader position are established before they run.
        await backfill_session_config_subjects()
        await backfill_session_subject_owners()
        await MemoryStore().backfill_observation_subjects()

        db.set_client(self.client)
        operations_service = OperationsService(db=db, task_registry=self.task_registry)
        set_operations_service(operations_service)
        operations_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting operations service (usually <1s)")
        await operations_service.start()
        logger.info("Operations service started in %.3fs", time.perf_counter() - operations_started_at)

        self.session_materializer.start(self.task_registry)

        session_warm_started_at = time.perf_counter()
        logger.info("[STARTUP] Warming local session cache (usually 1-4s)")
        await self._warm_local_sessions_cache()
        logger.info("Local session cache warm completed in %.3fs", time.perf_counter() - session_warm_started_at)

        adapter_start_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting adapters (usually 3-12s total)")
        await self.client.start()
        logger.info("Adapter startup completed in %.3fs", time.perf_counter() - adapter_start_started_at)

        await self._complete_startup_after_adapters()
        self._reminder_scheduler = self.task_registry.supervise(
            _REMINDER_SCHEDULER_TASK, partial(self.reminder_service.run, self.shutdown_event), restart=True
        )

        api_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting API server (usually 1-3s)")
        await self.api_server.start()
        self.api_server.set_on_server_exit(self.handle_api_server_exit)
        logger.info("API server started and cache wired in %.3fs", time.perf_counter() - api_started_at)
        self._schedule_worktree_home_reconciliation()
        self._schedule_final_output_reconciliation()

        event_consumers_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting event consumers (usually <1s)")
        await self._event_consumer_start()
        logger.info("Event consumers started in %.3fs", time.perf_counter() - event_consumers_started_at)

        # Close the startup snapshot/live gap through the same identity-based
        # materializer after the readers are active. Each ID is re-read at its
        # turn; no captured startup row can overtake a newer cache publication.
        session_reconcile_started_at = time.perf_counter()
        await self._warm_local_sessions_cache()
        logger.info(
            "Post-reader session reconciliation completed in %.3fs", time.perf_counter() - session_reconcile_started_at
        )

        project_warm_started_at = time.perf_counter()
        logger.info("[STARTUP] Warming local project cache (usually 2-5s)")
        await self.refresh_local_projects(ProjectRefreshTrigger.STARTUP)
        logger.info("Local project cache warm completed in %.3fs", time.perf_counter() - project_warm_started_at)

        self._started = True
        logger.info("Lifecycle startup completed in %.3fs", time.perf_counter() - startup_started_at)

    async def _complete_startup_after_adapters(self) -> None:
        """Finish startup tasks that require adapters and routing to be ready."""
        # Desk sessions that predate creation-time confinement are ended before
        # any queued input can reach them.
        await end_legacy_restricted_sessions(self.client)

        redis_transport_cache = self.client.transport
        if redis_transport_cache and hasattr(redis_transport_cache, "cache"):
            redis_transport_cache.cache = self.cache  # type: ignore[reportAttributeAccessIssue, unused-ignore]
            logger.info("Wired cache to Redis transport")

        logger.info("[STARTUP] Initializing voice handler (usually <1s)")
        self._init_voice_handler()
        logger.info("Voice handler initialized")

        processed_voice_count = await recover_voice_transcriptions(
            client=self.client, command_service=get_command_service()
        )
        if processed_voice_count:
            logger.info("Processed voice transcription startup work for %d row(s)", processed_voice_count)

        await get_operations_service().deliver_startup_recovery()
        await self._recover_session_startups()

        logger.info("[STARTUP] Starting inbound queue manager (usually <1s)")
        await get_inbound_queue_manager().startup()
        logger.info("Inbound queue manager started")
        repaired_conversation_count = await reconcile_outstanding_conversation_deliveries(
            config.computer.name,
            client=self.client,
            command_service=get_command_service(),
        )
        if repaired_conversation_count:
            logger.info("Repaired conversation delivery for %d mirrored segment(s)", repaired_conversation_count)

        omitted_intent_count = await reconcile_pending_discord_send_intents()
        if omitted_intent_count:
            logger.info(_DISCORD_SEND_INTENTS_RECONCILED_EVENT, omitted_count=omitted_intent_count)

    def _schedule_worktree_home_reconciliation(self) -> None:
        self.task_registry.spawn(
            self._reconcile_worktree_homes_for_local_projects(),
            name=_WORKTREE_HOME_RECONCILE_TASK,
        )

    async def _reconcile_worktree_homes_for_local_projects(self) -> None:
        projects = await command_handlers.list_projects_with_todos(self.degradations)
        for project in projects:
            if project.path:
                project_root = Path(project.path)
                await asyncio.to_thread(reconcile_worktree_homes, project_root, at_startup=True)
                await asyncio.to_thread(remove_vanished_worktree_trust, project_root)

    def _schedule_final_output_reconciliation(self) -> None:
        """Recover undelivered final output off the startup path, never inline.

        Recovery walks every session this computer owns and can perform network
        delivery per row, so running it before the request surface is listening
        holds the API socket closed for as long as the walk takes. It runs as a
        single background pass at whatever pace the walk takes; it carries no
        volume or rate budget.
        """
        self.task_registry.spawn(
            self._reconcile_final_outputs(),
            name=_FINAL_OUTPUT_RECONCILE_TASK,
        )

    async def _reconcile_final_outputs(self) -> None:
        """Repair undelivered final output once the request surface is available."""
        repaired_output_count = await self.client.reconcile_outstanding_final_outputs(config.computer.name)
        if repaired_output_count:
            logger.info("Attempted final output repair for %d session(s)", repaired_output_count)

    async def _warm_local_sessions_cache(self) -> None:
        """Seed cache with current local sessions for initial UI state."""
        warm_started_at = time.perf_counter()
        logger.trace("[PERF] _warm_local_sessions_cache start computer=%s", config.computer.name)
        try:
            list_started_at = time.perf_counter()
            sessions = await db.list_sessions(computer_name=config.computer.name, all_open=True)
            logger.trace(
                "[PERF] _warm_local_sessions_cache list_sessions dt=%.3f count=%d computer=%s",
                time.perf_counter() - list_started_at,
                len(sessions),
                config.computer.name,
            )
        except Exception as exc:
            logger.warning("Failed to warm session cache: %s", exc, exc_info=True)
            return

        if not sessions:
            logger.debug("No local sessions to seed in cache")
            logger.trace(
                "[PERF] _warm_local_sessions_cache done dt=%.3f count=0 computer=%s",
                time.perf_counter() - warm_started_at,
                config.computer.name,
            )
            return

        materialize_total_dt = 0.0
        for idx, session in enumerate(sessions, start=1):
            materialize_started_at = time.perf_counter()
            await self.session_materializer.reconcile(session.session_id)
            materialize_dt = time.perf_counter() - materialize_started_at
            materialize_total_dt += materialize_dt
            logger.trace(
                "[PERF] _warm_local_sessions_cache session=%s index=%d/%d reconcile_dt=%.3f",
                session.session_id,
                idx,
                len(sessions),
                materialize_dt,
            )

        warm_total_dt = time.perf_counter() - warm_started_at
        logger.trace(
            "[PERF] _warm_local_sessions_cache done dt=%.3f count=%d computer=%s",
            warm_total_dt,
            len(sessions),
            config.computer.name,
        )
        if warm_total_dt >= 5.0:
            logger.warning(
                (
                    "Local session cache warm was slow: total=%.3fs count=%d computer=%s "
                    "reconcile_total=%.3fs other=%.3fs"
                ),
                warm_total_dt,
                len(sessions),
                config.computer.name,
                materialize_total_dt,
                max(0.0, warm_total_dt - materialize_total_dt),
            )
        logger.info("Seeded cache with %d local sessions", len(sessions))

    async def refresh_local_projects(self, trigger: ProjectRefreshTrigger) -> None:
        """Refresh local project and todo snapshots from the project registry."""
        get_project_catalog_service().refresh()
        try:
            projects = await command_handlers.list_projects_with_todos(self.degradations)
        except Exception as exc:
            logger.warning("Failed to refresh local projects (trigger=%s): %s", trigger, exc, exc_info=True)
            raise

        computer_name = config.computer.name
        updated = self.cache.apply_projects_snapshot(computer_name, projects)
        if updated:
            logger.info("Refreshed cache with %d local projects (trigger=%s)", len(projects), trigger)

        # Apply empty snapshots too so removals clear the cached rows.
        todos_by_project: dict[str, list[TodoDTO]] = {}
        for p in projects:
            if p.path and p.todos:
                todos_by_project[p.path] = p.todos
        todos_updated = self.cache.apply_todos_snapshot(computer_name, todos_by_project)
        if todos_updated:
            logger.info("Seeded cache with todos for %d projects", len(todos_by_project))

    async def shutdown(self) -> None:
        """Stop core components in a defined order."""
        try:
            inbound = get_inbound_queue_manager()
        except RuntimeError:
            pass  # Not initialized — skip
        else:
            with cleanup_step(_INBOUND_SHUTDOWN_COMPONENT):
                await inbound.shutdown()
                logger.info("Inbound queue manager shut down")

        if self._reminder_scheduler:
            with cleanup_step(_REMINDER_SHUTDOWN_COMPONENT):
                await self._reminder_scheduler.cancel()

        if self.api_server:
            with cleanup_step(_API_SHUTDOWN_COMPONENT):
                await self.api_server.stop()
        for adapter_name, adapter in self.client.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            with cleanup_step(adapter_name):
                await adapter.stop()

        configure_session_source_reconciler(None)
        await self.session_materializer.stop()

        with cleanup_step(_STORAGE_SHUTDOWN_COMPONENT):
            await db.close()
        with cleanup_step(_TODOS_STORAGE_SHUTDOWN_COMPONENT):
            await close_workflow_stores()

    def handle_api_server_exit(
        self,
        surface: RequestSurface,
        exc: BaseException | None,
        started: bool | None,
        should_exit: bool | None,
        socket_exists: bool,
    ) -> None:
        """Handle a request-surface server exit and schedule restart from a central location."""
        if self.shutdown_event.is_set():
            return
        if should_exit:
            logger.info(
                _REQUEST_SURFACE_EXIT_CLEAN_EVENT,
                surface=surface,
                started=started,
                should_exit=should_exit,
                socket=socket_exists,
            )
            return
        kind = _ExitKind.CRASH if exc else _ExitKind.DONE
        reason = _EXIT_REASON.format(surface=surface, kind=kind)
        logger.warning(
            _REQUEST_SURFACE_EXIT_EVENT,
            surface=surface,
            reason=reason,
            started=started,
            socket=socket_exists,
        )
        self._schedule_api_restart(reason)

    def _schedule_api_restart(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error(_API_RESTART_NO_LOOP_EVENT, reason=reason)
            self._escalate(_API_RESTART_ESCALATION_REASON.format(reason=reason))
            return
        loop.create_task(self._restart_api_server(reason), name="api-server-restart")

    def schedule_api_restart(self, reason: str) -> None:
        """Request an API server restart from external watchdogs."""
        self._schedule_api_restart(reason)

    async def _restart_api_server(self, reason: str) -> bool:
        async with self._api_restart_lock:
            if self.shutdown_event.is_set():
                return False
            charge = self._api_restart_budget.charge(asyncio.get_running_loop().time())
            if not charge.within_budget:
                logger.error(
                    _API_RESTART_EXHAUSTED_EVENT,
                    reason=reason,
                    attempts=charge.attempt,
                    max_restarts=self._api_restart_budget.max_restarts,
                    window_s=self._api_restart_budget.window_s,
                )
                self._escalate(_API_RESTART_ESCALATION_REASON.format(reason=reason))
                return False

            logger.warning(
                "Restarting API server",
                reason=reason,
                attempt=charge.attempt,
                window_s=self._api_restart_budget.window_s,
                server_started=getattr(getattr(self.api_server, "server", None), "started", None),
                server_should_exit=getattr(getattr(self.api_server, "server", None), "should_exit", None),
                server_task_done=(
                    self.api_server.server_task.done() if self.api_server and self.api_server.server_task else None
                ),
            )
            await asyncio.sleep(self._api_restart_budget.backoff_s)
            api_server = self.api_server
            if not api_server:
                logger.error(_API_RESTART_UNAVAILABLE_EVENT)
                return False
            try:
                await api_server.restart_server()
                return True
            except Exception:
                logger.error(_API_RESTART_FAILED_EVENT, reason=reason, exc_info=True)
                self._schedule_api_restart(reason)
                return False
