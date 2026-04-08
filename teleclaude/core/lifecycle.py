"""Centralized daemon lifecycle management."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.api_server import APIServer
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.db.outbox_migration import migrate_outbox_on_startup
from teleclaude.core.models import SessionSnapshot
from teleclaude.core.operations import OperationsService, set_operations_service
from teleclaude.paths import MAIN_DB_PATH, TELECLAUDE_HOME

if TYPE_CHECKING:  # pragma: no cover
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class DaemonLifecycle:  # pylint: disable=too-many-instance-attributes
    """Own startup/shutdown ordering and API server restart policy."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        client: AdapterClient,
        cache: DaemonCache,
        shutdown_event: asyncio.Event,
        task_registry: TaskRegistry,
        runtime_settings: RuntimeSettings | None = None,
        log_background_task_exception: Callable[[str], Callable[[asyncio.Task[object]], None]],
        init_voice_handler: Callable[[], None],
        api_restart_max: int,
        api_restart_window_s: float,
        api_restart_backoff_s: float,
    ) -> None:
        self.client = client
        self.cache = cache
        self.runtime_settings = runtime_settings
        self.shutdown_event = shutdown_event
        self.task_registry = task_registry
        self._log_background_task_exception = log_background_task_exception
        self._init_voice_handler = init_voice_handler

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

        self.api_server = APIServer(
            self.client,
            cache=self.cache,
            task_registry=self.task_registry,
            runtime_settings=self.runtime_settings,
        )
        api_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting API server (usually 1-3s)")
        await self.api_server.start()
        self.api_server.set_on_server_exit(self.handle_api_server_exit)
        logger.info("API server started and cache wired in %.3fs", time.perf_counter() - api_started_at)

        project_warm_started_at = time.perf_counter()
        logger.info("[STARTUP] Warming local project cache (usually 2-5s)")
        await self._warm_local_projects_cache()
        logger.info("Local project cache warm completed in %.3fs", time.perf_counter() - project_warm_started_at)

        adapter_start_started_at = time.perf_counter()
        logger.info("[STARTUP] Starting adapters (usually 3-12s total)")
        await self.client.start()
        logger.info("Adapter startup completed in %.3fs", time.perf_counter() - adapter_start_started_at)
        repaired_output_count = await self.client.reconcile_outstanding_final_outputs(config.computer.name)
        if repaired_output_count:
            logger.info("Repaired final output delivery for %d session(s)", repaired_output_count)

        redis_transport_cache = self.client.adapters.get("redis")
        if redis_transport_cache and hasattr(redis_transport_cache, "cache"):
            redis_transport_cache.cache = self.cache  # type: ignore[reportAttributeAccessIssue, unused-ignore]
            logger.info("Wired cache to Redis transport")

        logger.info("[STARTUP] Initializing voice handler (usually <1s)")
        self._init_voice_handler()
        logger.info("Voice handler initialized")

        from teleclaude.core.inbound_queue import get_inbound_queue_manager  # pylint: disable=import-outside-toplevel

        logger.info("[STARTUP] Starting inbound queue manager (usually <1s)")
        await get_inbound_queue_manager().startup()
        logger.info("Inbound queue manager started")

        self._started = True
        logger.info("Lifecycle startup completed in %.3fs", time.perf_counter() - startup_started_at)

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
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
            from teleclaude.core import command_handlers  # pylint: disable=import-outside-toplevel

            projects = await command_handlers.list_projects_with_todos()
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
        from teleclaude.api_models import TodoDTO  # pylint: disable=import-outside-toplevel

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
            from teleclaude.core.inbound_queue import get_inbound_queue_manager  # noqa: I001  # pylint: disable=import-outside-toplevel

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
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("API server restart failed: %s", exc, exc_info=True)
                return False
