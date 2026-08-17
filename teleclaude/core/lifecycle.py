"""Centralized daemon lifecycle management."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord.message_ops import reconcile_pending_discord_send_intents
from teleclaude.api_server import APIServer
from teleclaude.config import config
from teleclaude.config.migrations import migrate_person_slugs_if_needed
from teleclaude.core.agent_coordinator._coordinator import seed_cutover_generations
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_delivery import reconcile_outstanding_conversation_deliveries
from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.db.outbox_migration import migrate_outbox_on_startup
from teleclaude.core.models import SessionSnapshot
from teleclaude.core.next_machine.delivery import reclaim_worktree_trash
from teleclaude.core.operations import OperationsService, set_operations_service
from teleclaude.core.voice_recovery import recover_voice_transcriptions
from teleclaude.paths import MAIN_DB_PATH, TELECLAUDE_HOME

if TYPE_CHECKING:  # pragma: no cover
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.reminders import ReminderService
    from teleclaude.core.task_registry import TaskRegistry
from teleclaude.api_models import TodoDTO
from teleclaude.core import command_handlers
from teleclaude.core.inbound_queue import get_inbound_queue_manager

logger = get_logger(__name__)

_CUTOVER_GENERATIONS_SEEDED_EVENT = "lifecycle_cutover_generations_seeded"
_DISCORD_SEND_INTENTS_RECONCILED_EVENT = "lifecycle_discord_send_intents_reconciled"

_WORKTREE_TRASH_RECLAIM_TASK = "worktree-trash-reclaim"
_FINAL_OUTPUT_RECONCILE_TASK = "final-output-reconcile"
_REMINDER_SCHEDULER_TASK = "reminder-scheduler"


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
        runtime_settings: RuntimeSettings | None = None,
        log_background_task_exception: Callable[[str], Callable[[asyncio.Task[object]], None]],
        init_voice_handler: Callable[[], None],
        event_platform_init: Callable[[], Awaitable[None]],
        event_consumer_start: Callable[[], Awaitable[None]],
        api_restart_max: int,
        api_restart_window_s: float,
        api_restart_backoff_s: float,
    ) -> None:
        self.client = client
        self.cache = cache
        self.runtime_settings = runtime_settings
        self.shutdown_event = shutdown_event
        self.task_registry = task_registry
        self.reminder_service = reminder_service
        self._log_background_task_exception = log_background_task_exception
        self._init_voice_handler = init_voice_handler
        self._event_platform_init = event_platform_init
        self._event_consumer_start = event_consumer_start

        self._api_restart_lock = asyncio.Lock()
        self._api_restart_attempts = 0
        self._api_restart_window_start = 0.0
        self._api_restart_max = api_restart_max
        self._api_restart_window_s = api_restart_window_s
        self._api_restart_backoff_s = api_restart_backoff_s
        self._started = False
        self.api_server: APIServer | None = None

    async def startup(self) -> None:
        """Start core components in a defined order."""
        if self._started:
            logger.warning("Lifecycle startup already completed; skipping")
            return
        startup_started_at = time.perf_counter()
        migrate_outbox_on_startup(str(MAIN_DB_PATH), str(get_outbox_db_path(TELECLAUDE_HOME)))
        migrate_person_slugs_if_needed()
        logger.info("[STARTUP] Initializing database (usually <1s)")
        await db.initialize()
        logger.info("Database initialized in %.3fs", time.perf_counter() - startup_started_at)

        db.set_client(self.client)
        operations_service = OperationsService(db=db, task_registry=self.task_registry)
        set_operations_service(operations_service)
        operations_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting operations service (usually <1s)")
        await operations_service.start()
        logger.info("Operations service started in %.3fs", time.perf_counter() - operations_started_at)

        session_warm_started_at = time.perf_counter()
        logger.info("[STARTUP] Warming local session cache (usually 1-4s)")
        await self._warm_local_sessions_cache()
        logger.info("Local session cache warm completed in %.3fs", time.perf_counter() - session_warm_started_at)

        # Construct the API server early so the event platform's websocket push
        # callback can wire into it, but DO NOT start it yet — adapters and the
        # event producer must be ready before any /todos/* operation can land.
        # The event *consumer* (stream processor + scheduler minute-clock) is the
        # inverse constraint: it must not start until this socket is bound, since
        # a consumer that self-calls the daemon's own API before the socket
        # exists fails with a connect error. See `_event_consumer_start` below.
        self.api_server = APIServer(
            self.client,
            cache=self.cache,
            task_registry=self.task_registry,
            runtime_settings=self.runtime_settings,
            reminder_service=self.reminder_service,
        )

        adapter_start_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting adapters (usually 3-12s total)")
        await self.client.start()
        logger.info("Adapter startup completed in %.3fs", time.perf_counter() - adapter_start_started_at)

        event_platform_started_at = time.perf_counter()
        logger.info("[STARTUP] Initializing event platform (usually <1s)")
        await self._event_platform_init()
        logger.info("Event platform initialized in %.3fs", time.perf_counter() - event_platform_started_at)

        await self._complete_startup_after_adapters()
        self.task_registry.spawn(
            self.reminder_service.run(self.shutdown_event),
            name=_REMINDER_SCHEDULER_TASK,
        )

        api_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting API server (usually 1-3s)")
        await self.api_server.start()
        self.api_server.set_on_server_exit(self.handle_api_server_exit)
        logger.info("API server started and cache wired in %.3fs", time.perf_counter() - api_started_at)
        self._schedule_worktree_trash_reclaim()
        self._schedule_final_output_reconciliation()

        event_consumers_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting event consumers (usually <1s)")
        await self._event_consumer_start()
        logger.info("Event consumers started in %.3fs", time.perf_counter() - event_consumers_started_at)

        project_warm_started_at = time.perf_counter()
        logger.info("[STARTUP] Warming local project cache (usually 2-5s)")
        await self._warm_local_projects_cache()
        logger.info("Local project cache warm completed in %.3fs", time.perf_counter() - project_warm_started_at)

        self._started = True
        logger.info("Lifecycle startup completed in %.3fs", time.perf_counter() - startup_started_at)

    async def _complete_startup_after_adapters(self) -> None:
        """Finish startup tasks that require adapters and routing to be ready."""
        # Cutover seeding must land before anything below can emit new-code
        # output: conversation delivery reconciliation and the inbound queue
        # manager (which can flush queued messages into delivery) are the
        # next two calls in this function. `client.adapters` is only
        # populated once `client.start()` returns, which is why this cannot
        # run any earlier in the startup sequence.
        seeded_count = await seed_cutover_generations(self.client)
        if seeded_count:
            logger.info(_CUTOVER_GENERATIONS_SEEDED_EVENT, seeded_count=seeded_count)

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

    def _schedule_worktree_trash_reclaim(self) -> None:
        """Schedule deferred worktree trash reclamation outside the startup path."""
        self.task_registry.spawn(
            self._reclaim_worktree_trash_for_local_projects(),
            name=_WORKTREE_TRASH_RECLAIM_TASK,
        )
        logger.info("Scheduled worktree trash reclaim")

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

    async def _reclaim_worktree_trash_for_local_projects(self) -> None:
        try:
            projects = await command_handlers.list_projects_with_todos()
        except Exception as exc:
            logger.warning("Failed to list projects for worktree trash reclaim: %s", exc, exc_info=True)
            return

        for project in projects:
            if not project.path:
                continue
            try:
                failures = await asyncio.to_thread(reclaim_worktree_trash, project.path)
            except Exception as exc:
                logger.warning("Worktree trash reclaim failed for project %s: %s", project.path, exc, exc_info=True)
                continue
            if failures:
                logger.warning(
                    "Worktree trash reclaim failed for %d entries in project %s: %s",
                    len(failures),
                    project.path,
                    failures,
                )

    async def _warm_local_sessions_cache(self) -> None:
        """Seed cache with current local sessions for initial UI state."""
        warm_started_at = time.perf_counter()
        logger.trace("[PERF] _warm_local_sessions_cache start computer=%s", config.computer.name)
        try:
            list_started_at = time.perf_counter()
            sessions = await db.list_sessions(computer_name=config.computer.name, include_headless=True)
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

        snapshot_total_dt = 0.0
        cache_update_total_dt = 0.0
        for idx, session in enumerate(sessions, start=1):
            snapshot_started_at = time.perf_counter()
            snapshot = SessionSnapshot.from_db_session(session, computer=config.computer.name)
            snapshot_dt = time.perf_counter() - snapshot_started_at
            snapshot_total_dt += snapshot_dt
            cache_update_started_at = time.perf_counter()
            self.cache.update_session(snapshot)
            cache_update_dt = time.perf_counter() - cache_update_started_at
            cache_update_total_dt += cache_update_dt
            logger.trace(
                "[PERF] _warm_local_sessions_cache session=%s index=%d/%d snapshot_dt=%.3f cache_update_dt=%.3f",
                session.session_id,
                idx,
                len(sessions),
                snapshot_dt,
                cache_update_dt,
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
                    "snapshot_total=%.3fs cache_update_total=%.3fs other=%.3fs"
                ),
                warm_total_dt,
                len(sessions),
                config.computer.name,
                snapshot_total_dt,
                cache_update_total_dt,
                max(0.0, warm_total_dt - snapshot_total_dt - cache_update_total_dt),
            )
        logger.info("Seeded cache with %d local sessions", len(sessions))

    async def _warm_local_projects_cache(self) -> None:
        """Seed cache with current local projects AND todos for instant UI."""
        try:
            projects = await command_handlers.list_projects_with_todos()
        except Exception as exc:
            logger.warning("Failed to warm projects cache: %s", exc, exc_info=True)
            return

        if not projects:
            logger.debug("No local projects to seed in cache")
            return

        computer_name = config.computer.name
        updated = self.cache.apply_projects_snapshot(computer_name, projects)
        if updated:
            logger.info("Seeded cache with %d local projects", len(projects))

        # Warm todo cache alongside projects
        todos_by_project: dict[str, list[TodoDTO]] = {}
        for p in projects:
            if p.path and p.todos:
                todos_by_project[p.path] = p.todos
        if todos_by_project:
            self.cache.apply_todos_snapshot(computer_name, todos_by_project)
            logger.info("Seeded cache with todos for %d projects", len(todos_by_project))

    async def shutdown(self) -> None:
        """Stop core components in a defined order."""
        try:
            await get_inbound_queue_manager().shutdown()
            logger.info("Inbound queue manager shut down")
        except RuntimeError:
            pass  # Not initialized — skip

        if self.api_server:
            await self.api_server.stop()
        for adapter_name, adapter in self.client.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            await adapter.stop()

        await db.close()

    def handle_api_server_exit(
        self,
        exc: BaseException | None,
        started: bool | None,
        should_exit: bool | None,
        socket_exists: bool,
    ) -> None:
        """Handle API server exit and schedule restart from a central location."""
        if self.shutdown_event.is_set():
            return
        if should_exit:
            logger.info(
                "API server exited cleanly; skipping restart",
                started=started,
                should_exit=should_exit,
                socket=socket_exists,
            )
            return
        reason = "api_task_crash" if exc else "api_task_done"
        logger.warning(
            "API server exit detected; scheduling restart",
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
            logger.error("No running event loop to restart API server (%s)", reason)
            self.shutdown_event.set()
            return
        loop.create_task(self._restart_api_server(reason), name="api-server-restart")

    def schedule_api_restart(self, reason: str) -> None:
        """Request an API server restart from external watchdogs."""
        self._schedule_api_restart(reason)

    async def _restart_api_server(self, reason: str) -> bool:
        async with self._api_restart_lock:
            if self.shutdown_event.is_set():
                return False
            now = asyncio.get_running_loop().time()
            if (
                self._api_restart_window_start == 0.0
                or (now - self._api_restart_window_start) > self._api_restart_window_s
            ):
                self._api_restart_window_start = now
                self._api_restart_attempts = 0

            self._api_restart_attempts += 1
            if self._api_restart_attempts > self._api_restart_max:
                logger.error(
                    "API server restart limit exceeded; leaving server down",
                    reason=reason,
                    attempts=self._api_restart_attempts,
                )
                return False

            logger.warning(
                "Restarting API server",
                reason=reason,
                attempt=self._api_restart_attempts,
                window_s=self._api_restart_window_s,
                server_started=getattr(getattr(self.api_server, "server", None), "started", None),
                server_should_exit=getattr(getattr(self.api_server, "server", None), "should_exit", None),
                server_task_done=(
                    self.api_server.server_task.done() if self.api_server and self.api_server.server_task else None
                ),
            )
            await asyncio.sleep(self._api_restart_backoff_s)
            api_server = self.api_server
            if not api_server:
                logger.error("API server not available; cannot restart")
                return False
            try:
                await api_server.restart_server()
                return True
            except Exception as exc:
                logger.error("API server restart failed: %s", exc, exc_info=True)
                return False
