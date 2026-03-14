"""Connection management for RedisTransport: connect, reconnect, start, stop."""

from __future__ import annotations

import asyncio
import random
import ssl
import time
from typing import TYPE_CHECKING, TypeAlias

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

logger = get_logger(__name__)

_RedisKwargValue: TypeAlias = str | int | float | bool | None | ssl.VerifyMode

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry


class _ConnectionMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: Redis connection lifecycle, reconnect loop, start/stop."""

    if TYPE_CHECKING:
        task_registry: TaskRegistry | None
        _connection_task: asyncio.Task[object] | None
        _message_poll_task: asyncio.Task[object] | None
        _heartbeat_task: asyncio.Task[object] | None
        _peer_refresh_task: asyncio.Task[object] | None
        _reconnect_task: asyncio.Task[object] | None
        _running: bool
        _idle_poll_last_log_at: float | None
        _idle_poll_suppressed: int
        _redis_ready: asyncio.Event
        _redis_last_error: str | None
        redis: Redis
        redis_url: str
        redis_password: str | None
        max_connections: int
        socket_timeout: float | None
        message_stream_maxlen: int
        output_stream_maxlen: int

        @property
        def cache(self) -> DaemonCache | None: ...

        async def _poll_redis_messages(self) -> None: ...
        async def _heartbeat_loop(self) -> None: ...
        async def _peer_refresh_loop(self) -> None: ...
        async def refresh_remote_snapshot(self) -> None: ...

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

    def _log_task_exception(self, task: asyncio.Task[object]) -> None:
        """
        Log exceptions from untracked background tasks.

        Used as done callback for tasks spawned without TaskRegistry to prevent
        silent failures.

        Args:
            task: The completed task
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Untracked task %s failed: %s", task.get_name(), exc, exc_info=exc)

    async def start(self) -> None:
        """Initialize Redis connection and start background tasks."""
        if self._running:
            logger.warning("RedisTransport already running")
            return

        self._running = True

        # Start connection orchestration without blocking daemon boot
        if self.task_registry:
            self._connection_task = self.task_registry.spawn(
                self._ensure_connection_and_start_tasks(), name="redis-connection"
            )
        else:
            # Fallback: untracked task with explicit exception logging
            self._connection_task = asyncio.create_task(
                self._ensure_connection_and_start_tasks(), name="redis-connection"
            )
            self._connection_task.add_done_callback(self._log_task_exception)
        logger.info("RedisTransport start triggered (connection handled asynchronously)")

    async def _ensure_connection_and_start_tasks(self) -> None:
        """Connect and launch background tasks with retry, without blocking daemon startup."""

        self._schedule_reconnect("startup")
        await self._await_redis_ready()

        if not self._running:
            return

        await self._populate_initial_cache()

        # Start background tasks once connected
        if self.task_registry:
            self._message_poll_task = self.task_registry.spawn(self._poll_redis_messages(), name="redis-message-poll")
            self._heartbeat_task = self.task_registry.spawn(self._heartbeat_loop(), name="redis-heartbeat")
            self._peer_refresh_task = self.task_registry.spawn(self._peer_refresh_loop(), name="redis-peer-refresh")
        else:
            self._message_poll_task = asyncio.create_task(self._poll_redis_messages())
            self._message_poll_task.add_done_callback(self._log_task_exception)
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._heartbeat_task.add_done_callback(self._log_task_exception)
            self._peer_refresh_task = asyncio.create_task(self._peer_refresh_loop())
            self._peer_refresh_task.add_done_callback(self._log_task_exception)

        logger.info("RedisTransport connected and background tasks started")

    async def _populate_initial_cache(self) -> None:
        """Populate cache with remote computers and projects on startup."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping initial cache population")
            return

        logger.info("Populating initial cache from remote computers...")
        await self.refresh_remote_snapshot()

    def _create_redis_client(self) -> Redis:
        """Create a Redis client with the configured settings."""
        kwargs: dict[str, _RedisKwargValue] = {
            "password": self.redis_password,
            "max_connections": self.max_connections,
            "socket_timeout": self.socket_timeout,
            "health_check_interval": 10,
            "decode_responses": False,
        }
        if self.redis_url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
        return Redis.from_url(self.redis_url, **kwargs)

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

    def _schedule_reconnect(self, reason: str, error: Exception | None = None) -> None:
        """Ensure a single reconnect loop is running."""
        if not self._running:
            return
        self._redis_ready.clear()
        if error is not None:
            self._redis_last_error = str(error)
        if self._reconnect_task and not self._reconnect_task.done():
            return
        logger.warning("Redis connection unhealthy; scheduling reconnect (reason=%s)", reason)
        if self.task_registry:
            self._reconnect_task = self.task_registry.spawn(self._reconnect_loop(reason), name="redis-reconnect")
        else:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop(reason), name="redis-reconnect")
            self._reconnect_task.add_done_callback(self._log_task_exception)

    async def _reconnect_loop(self, reason: str) -> None:
        """Reconnect loop with capped backoff and jitter."""
        delay = 1.0
        while self._running:
            try:
                if self.redis:
                    try:
                        await asyncio.wait_for(self.redis.aclose(), timeout=2.0)
                    except (TimeoutError, Exception):
                        # Force-disconnect stale pool to avoid fd leaks
                        try:
                            await self.redis.connection_pool.disconnect(inuse_connections=True)
                        except Exception:
                            pass
                self.redis = self._create_redis_client()
                await self.redis.ping()  # pyright: ignore[reportGeneralTypeIssues]
                self._redis_ready.set()
                logger.info("Redis connection ready (reason=%s)", reason)
                return
            except Exception as exc:  # broad to avoid crash loops
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

    async def stop(self) -> None:
        """Stop adapter and cleanup resources."""
        if not self._running:
            return

        self._running = False

        # Cancel connection orchestrator
        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Cancel background tasks
        if self._message_poll_task:
            self._message_poll_task.cancel()
            self._message_poll_task = None

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._peer_refresh_task:
            self._peer_refresh_task.cancel()
            try:
                await self._peer_refresh_task
            except asyncio.CancelledError:
                pass

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

        logger.info("RedisTransport stopped")
