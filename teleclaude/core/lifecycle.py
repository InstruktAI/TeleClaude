"""Centralized daemon lifecycle management."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.rest_adapter import RESTAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.models import SessionSummary

if TYPE_CHECKING:  # pragma: no cover
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry
    from teleclaude.mcp_server import TeleClaudeMCPServer

logger = get_logger(__name__)


class DaemonLifecycle:
    """Own startup/shutdown ordering and REST restart policy."""

    def __init__(
        self,
        *,
        client: "AdapterClient",
        cache: "DaemonCache",
        mcp_server: Optional["TeleClaudeMCPServer"],
        shutdown_event: asyncio.Event,
        task_registry: "TaskRegistry",
        log_background_task_exception: Callable[[str], Callable[[asyncio.Task[object]], None]],
        handle_mcp_task_done: Callable[[asyncio.Task[object]], None],
        mcp_watch_factory: Callable[[], asyncio.Task[object]],
        set_last_mcp_restart_at: Callable[[float], None],
        init_voice_handler: Callable[[], None],
        rest_restart_max: int,
        rest_restart_window_s: float,
        rest_restart_backoff_s: float,
    ) -> None:
        self.client = client
        self.cache = cache
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

        self._rest_restart_lock = asyncio.Lock()
        self._rest_restart_attempts = 0
        self._rest_restart_window_start = 0.0
        self._rest_restart_max = rest_restart_max
        self._rest_restart_window_s = rest_restart_window_s
        self._rest_restart_backoff_s = rest_restart_backoff_s
        self._started = False

    async def startup(self) -> None:
        """Start core components in a defined order."""
        if self._started:
            logger.warning("Lifecycle startup already completed; skipping")
            return
        await db.initialize()
        logger.info("Database initialized")

        db.set_client(self.client)
        await self._warm_local_sessions_cache()

        await self.client.start()

        rest_adapter = self.client.adapters.get("rest")
        if isinstance(rest_adapter, RESTAdapter):
            rest_adapter.cache = self.cache  # type: ignore[reportAttributeAccessIssue, unused-ignore]
            rest_adapter.set_on_server_exit(self.handle_rest_server_exit)
            logger.info("Wired cache to REST adapter")
        else:
            logger.warning("REST adapter not available for cache wiring")

        redis_adapter_cache = self.client.adapters.get("redis")
        if redis_adapter_cache and hasattr(redis_adapter_cache, "cache"):
            redis_adapter_cache.cache = self.cache  # type: ignore[reportAttributeAccessIssue, unused-ignore]
            logger.info("Wired cache to Redis adapter")

        self._init_voice_handler()
        logger.info("Voice handler initialized")

        redis_adapter_base = self.client.adapters.get("redis")
        if redis_adapter_base and isinstance(redis_adapter_base, RedisAdapter):
            redis_adapter: RedisAdapter = redis_adapter_base
            if redis_adapter.redis:
                status_key = f"system_status:{config.computer.name}:deploy"
                status_data = await redis_adapter.redis.get(status_key)
                if status_data:
                    try:
                        status_raw: object = json.loads(status_data.decode("utf-8"))  # type: ignore[misc]
                        if isinstance(status_raw, dict) and status_raw.get("status") == "restarting":  # type: ignore[misc]
                            await redis_adapter.redis.set(
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

        await db.close()

    def handle_rest_server_exit(
        self,
        exc: BaseException | None,
        started: bool | None,
        should_exit: bool | None,
        socket_exists: bool,
    ) -> None:
        """Handle REST server exit and schedule restart from a central location."""
        if self.shutdown_event.is_set():
            return
        if should_exit:
            logger.info(
                "REST server exited cleanly; skipping restart",
                started=started,
                should_exit=should_exit,
                socket=socket_exists,
            )
            return
        reason = "rest_task_crash" if exc else "rest_task_done"
        logger.warning(
            "REST server exit detected; scheduling restart",
            reason=reason,
            started=started,
            socket=socket_exists,
        )
        self._schedule_rest_restart(reason)

    def _schedule_rest_restart(self, reason: str) -> None:
        if self.shutdown_event.is_set():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("No running event loop to restart REST server (%s)", reason)
            self.shutdown_event.set()
            return
        loop.create_task(self._restart_rest_server(reason))

    async def _restart_rest_server(self, reason: str) -> bool:
        async with self._rest_restart_lock:
            if self.shutdown_event.is_set():
                return False
            now = asyncio.get_running_loop().time()
            if (
                self._rest_restart_window_start == 0.0
                or (now - self._rest_restart_window_start) > self._rest_restart_window_s
            ):
                self._rest_restart_window_start = now
                self._rest_restart_attempts = 0

            self._rest_restart_attempts += 1
            if self._rest_restart_attempts > self._rest_restart_max:
                logger.error(
                    "REST restart limit exceeded; leaving server down",
                    reason=reason,
                    attempts=self._rest_restart_attempts,
                )
                return False

            logger.warning(
                "Restarting REST server",
                reason=reason,
                attempt=self._rest_restart_attempts,
                window_s=self._rest_restart_window_s,
            )
            await asyncio.sleep(self._rest_restart_backoff_s)
            rest_adapter = self.client.adapters.get("rest")
            if not isinstance(rest_adapter, RESTAdapter):
                logger.error("REST adapter not available; cannot restart")
                return False
            try:
                await rest_adapter.restart_server()
                return True
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("REST restart failed: %s", exc, exc_info=True)
                return False
