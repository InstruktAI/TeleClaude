"""Connection management for RedisTransport: connect, reconnect, start, stop."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from teleclaude.core.cleanup_step import cleanup_step
from teleclaude.transport.redis_client import create_redis_client

logger = get_logger(__name__)


if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

_TRANSPORT_RUNTIME_TASK = "redis-transport"
_RECONNECT_TASK = "redis-reconnect"
_MESSAGE_POLL_LOOP = "redis-message-poll"
_HEARTBEAT_LOOP = "redis-heartbeat"
_PEER_REFRESH_LOOP = "redis-peer-refresh"
_PROJECTS_DIGEST_LOOP = "redis-projects-digest"
_STARTUP_RECONNECT_REASON = "startup"
_RECONNECT_CLEANUP_COMPONENT = "redis_reconnect"
_LOOP_ENDED = "Redis transport loop {name} ended while the transport was running"


class TransportLoopEnded(Exception):
    """A transport loop returned while the transport was running, so the transport's run ends."""


class _ConnectionMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: Redis connection lifecycle, reconnect loop, start/stop."""

    if TYPE_CHECKING:
        task_registry: TaskRegistry
        _transport_runtime: SupervisedTask | None
        _reconnect_task: asyncio.Task[object] | None
        _running: bool
        _idle_poll_last_log_at: float | None
        _idle_poll_suppressed: int
        _redis_ready: asyncio.Event
        _redis_last_error: str | None
        redis: Redis
        redis_url: str
        redis_username: str | None
        redis_password: str | None
        max_connections: int
        socket_timeout: float | None
        message_stream_maxlen: int
        output_stream_maxlen: int

        @property
        def cache(self) -> DaemonCache | None:
            """Return the shared daemon cache."""
            raise NotImplementedError

        async def _poll_redis_messages(self) -> None:
            """Poll the Redis message stream."""
            raise NotImplementedError

        async def _heartbeat_loop(self) -> None:
            """Emit periodic Redis heartbeats."""
            raise NotImplementedError

        async def _peer_refresh_loop(self) -> None:
            """Refresh peer metadata from heartbeats."""
            raise NotImplementedError

        async def _projects_digest_loop(self) -> None:
            """Keep the advertised projects digest current."""
            raise NotImplementedError

        async def refresh_remote_snapshot(self) -> None:
            """Populate cache snapshots from remote peers."""
            raise NotImplementedError

    def _reset_idle_poll_log_throttle(self) -> None:
        self._idle_poll_last_log_at = None
        self._idle_poll_suppressed = 0

    def _maybe_log_idle_poll(self, *, message_stream: str, now: float | None = None) -> None:
        """Throttle "idle" polling logs to avoid tail spam.

        When Redis has no messages, the adapter polls every ~1s. Logging that fact every
        iteration is high-noise, especially at DEBUG. Instead, emit at most once per 60s
        and include how many idle polls were suppressed.
        """
        now = time.monotonic() if now is None else now

        if self._idle_poll_last_log_at is None:
            self._idle_poll_last_log_at = now

        self._idle_poll_suppressed += 1

        elapsed_s = now - self._idle_poll_last_log_at
        if elapsed_s < 60.0:
            return

        logger.trace(
            "No messages received, continuing poll loop",
            stream=message_stream,
            suppressed=self._idle_poll_suppressed,
            interval_s=int(elapsed_s),
        )
        self._idle_poll_last_log_at = now
        self._idle_poll_suppressed = 0

    @property
    def is_redis_ready(self) -> bool:
        """Whether Redis has connected at least once (non-blocking read)."""
        return self._redis_ready.is_set()

    async def start(self) -> None:
        """Initialize Redis connection and start background tasks."""
        if self._running:
            logger.warning("RedisTransport already running")
            return

        self._running = True

        # Start connection orchestration without blocking daemon boot
        self._transport_runtime = self.task_registry.supervise(
            _TRANSPORT_RUNTIME_TASK, self._run_transport, restart=True
        )
        logger.info("RedisTransport start triggered (connection handled asynchronously)")

    async def _run_transport(self) -> None:
        """Run the transport: connect, fill the cache, then run the message poll, heartbeat and peer refresh as one unit.

        Any of the three loops ending while the transport is running ends the run and cancels the others, so the
        supervisor replaces the whole unit: it reconnects when needed, fills the cache again and restarts all three.
        """
        if not self._redis_ready.is_set():
            self._schedule_reconnect(_STARTUP_RECONNECT_REASON)
        await self._await_redis_ready()

        if not self._running:
            return

        await self._populate_initial_cache()

        logger.info("RedisTransport connected and background tasks started")
        async with asyncio.TaskGroup() as group:
            group.create_task(self._run_loop_while_running(_MESSAGE_POLL_LOOP, self._poll_redis_messages))
            group.create_task(self._run_loop_while_running(_HEARTBEAT_LOOP, self._heartbeat_loop))
            group.create_task(self._run_loop_while_running(_PEER_REFRESH_LOOP, self._peer_refresh_loop))
            group.create_task(self._run_loop_while_running(_PROJECTS_DIGEST_LOOP, self._projects_digest_loop))

    async def _run_loop_while_running(self, name: str, loop: Callable[[], Awaitable[None]]) -> None:
        """Run a transport loop; its return while the transport runs and is not being cancelled is an end of the run."""
        await loop()
        current = asyncio.current_task()
        if self._running and current is not None and current.cancelling() == 0:
            raise TransportLoopEnded(_LOOP_ENDED.format(name=name))

    async def _populate_initial_cache(self) -> None:
        """Populate cache with remote computers and projects on startup."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping initial cache population")
            return

        logger.info("Populating initial cache from remote computers...")
        await self.refresh_remote_snapshot()

    def _create_redis_client(self) -> Redis:
        """Create a Redis client with the configured settings."""
        return create_redis_client(
            self.redis_url,
            username=self.redis_username,
            password=self.redis_password,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
        )

    async def _await_redis_ready(self) -> None:
        """Wait until Redis connection is ready or transport stops."""
        while self._running:
            await self._redis_ready.wait()
            if self.redis:
                return
        raise RuntimeError("Redis transport stopped")

    async def _get_redis(self) -> Redis:
        """Return a connected Redis client (waits for readiness)."""
        await self._await_redis_ready()
        return self.redis

    async def get_redis(self) -> Redis:
        """Return a connected Redis client for public callers."""
        return await self._get_redis()

    def _schedule_reconnect(self, reason: str, error: Exception | None = None) -> None:
        """Ensure a single reconnect loop is running."""
        if not self._running:
            return
        self._redis_ready.clear()
        if error is not None:
            self._redis_last_error = str(error)
        if self._reconnect_task and not self._reconnect_task.done():
            return
        if reason == "startup":
            logger.info("Redis startup connect scheduled")
        else:
            logger.warning("Redis connection unhealthy; scheduling reconnect (reason=%s)", reason)
        self._reconnect_task = self.task_registry.spawn(self._reconnect_loop(reason), name=_RECONNECT_TASK)

    async def _reconnect_loop(self, reason: str) -> None:
        """Reconnect loop with capped backoff and jitter."""
        delay = 1.0
        while self._running:
            try:
                await self._close_existing_redis()
                self.redis = self._create_redis_client()
                await self.redis.ping()  # pyright: ignore[reportGeneralTypeIssues]
                self._redis_ready.set()
                logger.info("Redis connection ready (reason=%s)", reason)
                return
            except (RedisError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
                logger.error("Redis reconnection failed (retry in %ss): %s", int(delay), exc)
                await asyncio.sleep(delay + random.random())
                delay = min(delay * 2.0, 10.0)

        logger.info("Stopped redis reconnection attempts (adapter no longer running)")

    async def _handle_redis_error(self, context: str, exc: Exception) -> None:
        """Centralize Redis error handling and recovery."""
        logger.error("%s: %s", context, exc)
        self._schedule_reconnect(context, exc)
        try:
            await self._await_redis_ready()
        except RuntimeError:
            return

    async def _close_existing_redis(self) -> None:
        """Close the current Redis client, force-disconnecting on timeout."""
        if not self.redis:
            return

        try:
            await asyncio.wait_for(self.redis.aclose(), timeout=2.0)
            return
        except (RedisError, OSError, RuntimeError, TimeoutError, ValueError):
            pass

        await self._disconnect_stale_pool()

    async def _disconnect_stale_pool(self) -> None:
        """Disconnect all pooled Redis connections after a failed close."""
        try:
            await self.redis.connection_pool.disconnect(inuse_connections=True)
        except (RedisError, OSError, RuntimeError, ValueError):
            logger.debug("Ignoring stale Redis pool disconnect failure", exc_info=True)

    async def stop(self) -> None:
        """Stop adapter and cleanup resources."""
        if not self._running:
            return

        self._running = False

        # Stop the transport runtime: it cancels the message poll, heartbeat and peer refresh with it
        if self._transport_runtime:
            await self._transport_runtime.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with cleanup_step(_RECONNECT_CLEANUP_COMPONENT):
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

        logger.info("RedisTransport stopped")
