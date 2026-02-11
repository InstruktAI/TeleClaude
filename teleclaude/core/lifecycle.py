"""Centralized daemon lifecycle management."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.api_server import APIServer
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.models import SessionSummary
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:  # pragma: no cover
    from teleclaude.config.runtime_settings import RuntimeSettings
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry
    from teleclaude.mcp_server import TeleClaudeMCPServer

logger = get_logger(__name__)


class DaemonLifecycle:
    """Own startup/shutdown ordering and API server restart policy."""

    def __init__(
        self,
        *,
        client: "AdapterClient",
        cache: "DaemonCache",
        mcp_server: Optional["TeleClaudeMCPServer"],
        shutdown_event: asyncio.Event,
        task_registry: "TaskRegistry",
        runtime_settings: "RuntimeSettings | None" = None,
        log_background_task_exception: Callable[[str], Callable[[asyncio.Task[object]], None]],
        handle_mcp_task_done: Callable[[asyncio.Task[object]], None],
        mcp_watch_factory: Callable[[], asyncio.Task[object]],
        set_last_mcp_restart_at: Callable[[float], None],
        init_voice_handler: Callable[[], None],
        api_restart_max: int,
        api_restart_window_s: float,
        api_restart_backoff_s: float,
    ) -> None:
        self.client = client
        self.cache = cache
        self.runtime_settings = runtime_settings
        self.mcp_server = mcp_server
        self.shutdown_event = shutdown_event
        self.task_registry = task_registry
        self._log_background_task_exception = log_background_task_exception
        self._handle_mcp_task_done = handle_mcp_task_done
        self._mcp_watch_factory = mcp_watch_factory
        self._set_last_mcp_restart_at = set_last_mcp_restart_at
        self._init_voice_handler = init_voice_handler

        self.mcp_task: asyncio.Task[object] | None = None
        self.mcp_watch_task: asyncio.Task[object] | None = None

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
        await db.initialize()
        logger.info("Database initialized")

        db.set_client(self.client)
        await self._warm_local_sessions_cache()
        await self._warm_local_projects_cache()

        await self.client.start()

        self.api_server = APIServer(
            self.client,
            cache=self.cache,
            task_registry=self.task_registry,
            runtime_settings=self.runtime_settings,
        )
        await self.api_server.start()
        self.api_server.set_on_server_exit(self.handle_api_server_exit)
        logger.info("API server started and cache wired")

        redis_transport_cache = self.client.adapters.get("redis")
        if redis_transport_cache and hasattr(redis_transport_cache, "cache"):
            redis_transport_cache.cache = self.cache  # type: ignore[reportAttributeAccessIssue, unused-ignore]
            logger.info("Wired cache to Redis transport")

        self._init_voice_handler()
        logger.info("Voice handler initialized")

        redis_transport_base = self.client.adapters.get("redis")
        if redis_transport_base and isinstance(redis_transport_base, RedisTransport):
            redis_transport: RedisTransport = redis_transport_base
            if redis_transport.redis:
                status_key = f"system_status:{config.computer.name}:deploy"
                if not redis_transport._redis_ready.is_set():  # pylint: disable=protected-access
                    logger.warning("Redis not ready; skipping deploy status check")
                    status_data = None
                else:
                    try:
                        status_data = await asyncio.wait_for(redis_transport.redis.get(status_key), timeout=1.0)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        logger.error("Failed to read deploy status from Redis: %s", exc, exc_info=True)
                        status_data = None
                if status_data:
                    try:
                        status_raw: object = json.loads(status_data.decode("utf-8"))  # type: ignore[misc]
                        if isinstance(status_raw, dict) and status_raw.get("status") == "restarting":  # type: ignore[misc]
                            await redis_transport.redis.set(
                                status_key,
                                json.dumps({"status": "deployed", "timestamp": time.time(), "pid": os.getpid()}),  # type: ignore[misc]
                            )
                            logger.info("Deployment complete, daemon restarted successfully (PID: %s)", os.getpid())
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning("Failed to parse deploy status: %s", e)

        logger.debug("MCP server object exists: %s", self.mcp_server is not None)
        if self.mcp_server:
            self.mcp_task = asyncio.create_task(self.mcp_server.start())
            self.mcp_task.add_done_callback(self._log_background_task_exception("mcp_server"))
            self.mcp_task.add_done_callback(self._handle_mcp_task_done)
            self._set_last_mcp_restart_at(asyncio.get_running_loop().time())
            logger.info("MCP server starting in background")

            self.mcp_watch_task = self._mcp_watch_factory()
            self.mcp_watch_task.add_done_callback(self._log_background_task_exception("mcp_watch"))
            logger.info("MCP server watch task started")
        else:
            logger.warning("MCP server not started - object is None")
        self._started = True

    async def _warm_local_sessions_cache(self) -> None:
        """Seed cache with current local sessions for initial UI state."""
        try:
            sessions = await db.list_sessions(computer_name=config.computer.name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to warm session cache: %s", exc, exc_info=True)
            return

        if not sessions:
            logger.debug("No local sessions to seed in cache")
            return

        for session in sessions:
            summary = SessionSummary.from_db_session(session, computer=config.computer.name)
            self.cache.update_session(summary)

        logger.info("Seeded cache with %d local sessions", len(sessions))

    async def _warm_local_projects_cache(self) -> None:
        """Seed cache with current local projects for digest/initial UI state."""
        try:
            from teleclaude.core import command_handlers

            projects = await command_handlers.list_projects()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to warm projects cache: %s", exc, exc_info=True)
            return

        if not projects:
            logger.debug("No local projects to seed in cache")
            return

        updated = self.cache.apply_projects_snapshot(config.computer.name, projects)
        if updated:
            logger.info("Seeded cache with %d local projects", len(projects))

    async def shutdown(self) -> None:
        """Stop core components in a defined order."""
        if self.mcp_task:
            self.mcp_task.cancel()
            try:
                await self.mcp_task
            except asyncio.CancelledError:
                pass
            logger.info("MCP server stopped")

        if self.mcp_watch_task:
            self.mcp_watch_task.cancel()
            try:
                await self.mcp_watch_task
            except asyncio.CancelledError:
                pass
            logger.info("MCP server watch task stopped")

        for adapter_name, adapter in self.client.adapters.items():
            logger.info("Stopping %s adapter...", adapter_name)
            await adapter.stop()
        if self.api_server:
            await self.api_server.stop()

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
        loop.create_task(self._restart_api_server(reason))

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
