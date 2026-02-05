"""Redis adapter for AI-to-AI communication via Redis Streams.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

# pylint: disable=too-many-instance-attributes

from __future__ import annotations

import asyncio
import base64
import json
import random
import ssl
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Optional, cast

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.constants import REDIS_REFRESH_COOLDOWN_SECONDS
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    DeployArgs,
    SessionLifecycleContext,
    SessionUpdatedContext,
    SystemCommandContext,
    TeleClaudeEvents,
    build_agent_payload,
    parse_command_string,
)
from teleclaude.core.feedback import get_last_feedback
from teleclaude.core.models import (
    ChannelMetadata,
    ComputerInfo,
    MessageMetadata,
    PeerInfo,
    ProjectInfo,
    RedisInboundMessage,
    RedisTransportMetadata,
    Session,
    SessionLaunchIntent,
    SessionSummary,
    ThinkingMode,
    TodoInfo,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.core.redis_utils import scan_keys
from teleclaude.types import SystemStats
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class RedisTransport(BaseAdapter, RemoteExecutionProtocol):  # pylint: disable=too-many-instance-attributes  # Redis transport requires many connection and state attributes
    """Transport for AI-to-AI communication via Redis Streams.

    Uses Redis Streams for reliable, ordered message delivery between computers.

    Implements RemoteExecutionProtocol for cross-computer orchestration.

    Architecture:
    - Each computer polls its message stream: messages:{computer_name}
    - Request/response replies are sent on output:{computer}:{message_id} streams
    - Computer registry uses Redis keys with TTL for heartbeats

    Message flow:
    - Comp1 → XADD messages:comp2 → Comp2 polls → executes message
    - Comp2 → XADD output:{computer}:{message_id} → Comp1 reads response for request/response
    """

    _ALLOWED_REFRESH_REASONS = {"startup", "digest", "interest", "ttl"}

    def __init__(self, adapter_client: "AdapterClient", task_registry: "TaskRegistry | None" = None):
        """Initialize Redis transport.

        Args:
            adapter_client: AdapterClient instance for event emission
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        super().__init__()

        # Store client reference (ONLY interface to daemon)
        self.client = adapter_client
        event_bus.subscribe(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)
        event_bus.subscribe(TeleClaudeEvents.SESSION_STARTED, self._handle_session_started)
        event_bus.subscribe(TeleClaudeEvents.SESSION_CLOSED, self._handle_session_closed)

        # Task registry for tracked background tasks
        self.task_registry = task_registry

        # Cache reference (wired by daemon after start via property setter)
        self._cache: "DaemonCache | None" = None

        # Transport state
        self._message_poll_task: Optional[asyncio.Task[object]] = None
        self._heartbeat_task: Optional[asyncio.Task[object]] = None
        self._session_events_poll_task: Optional[asyncio.Task[object]] = None
        self._peer_refresh_task: Optional[asyncio.Task[object]] = None
        self._connection_task: Optional[asyncio.Task[object]] = None
        self._reconnect_task: Optional[asyncio.Task[object]] = None
        self._running = False
        self._redis_ready = asyncio.Event()
        self._redis_last_error: str | None = None

        # Extract Redis configuration from global config
        self.redis_url = config.redis.url
        self.redis_password = config.redis.password
        self.computer_name = config.computer.name

        # Redis connection settings
        self.max_connections = config.redis.max_connections
        self.socket_timeout = config.redis.socket_timeout

        # Stream configuration
        self.message_stream_maxlen = config.redis.message_stream_maxlen
        self.output_stream_maxlen = config.redis.output_stream_maxlen
        self.output_stream_ttl = config.redis.output_stream_ttl

        # Heartbeat config
        self.heartbeat_interval = 30  # Send heartbeat every 30s
        self.heartbeat_ttl = 60  # Key expires after 60s

        # Track pending new_session requests for response
        self._pending_new_session_request: Optional[str] = None

        # Track last-seen project digests for peers
        self._peer_digests: dict[str, str] = {}

        # Remote refresh coalescing (per peer + data type)
        self._refresh_cooldown_seconds = REDIS_REFRESH_COOLDOWN_SECONDS
        self._refresh_last: dict[str, float] = {}
        self._refresh_tasks: dict[str, asyncio.Task[object]] = {}

        # Initialize redis client placeholder (actual connection established in start)
        self.redis: Redis = self._create_redis_client()
        self._redis_ready.clear()

        # Idle poll logging throttling (avoid tail spam at DEBUG level)
        self._idle_poll_last_log_at: float | None = None
        self._idle_poll_suppressed: int = 0

        logger.info("RedisTransport initialized for computer: %s", self.computer_name)

    @property
    def cache(self) -> "DaemonCache | None":
        """Get cache reference."""
        return self._cache

    @cache.setter
    def cache(self, value: "DaemonCache | None") -> None:
        """Set cache reference and subscribe to changes."""
        if self._cache:
            self._cache.unsubscribe(self._on_cache_change)
        self._cache = value
        if value:
            value.subscribe(self._on_cache_change)
            logger.info("Redis adapter subscribed to cache notifications")

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
            self._session_events_poll_task = self.task_registry.spawn(
                self._poll_session_events(), name="redis-session-events"
            )
        else:
            self._message_poll_task = asyncio.create_task(self._poll_redis_messages())
            self._message_poll_task.add_done_callback(self._log_task_exception)
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._heartbeat_task.add_done_callback(self._log_task_exception)
            self._peer_refresh_task = asyncio.create_task(self._peer_refresh_loop())
            self._peer_refresh_task.add_done_callback(self._log_task_exception)
            self._session_events_poll_task = asyncio.create_task(self._poll_session_events())
            self._session_events_poll_task.add_done_callback(self._log_task_exception)

        logger.info("RedisTransport connected and background tasks started")

    async def _populate_initial_cache(self) -> None:
        """Populate cache with remote computers and projects on startup."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping initial cache population")
            return

        logger.info("Populating initial cache from remote computers...")
        await self.refresh_remote_snapshot()

    async def refresh_remote_snapshot(self) -> None:
        """Refresh remote computers and project/todo cache (best effort)."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping remote snapshot refresh")
            return

        logger.info("Refreshing remote cache snapshot...")

        peers = await self.discover_peers()
        for peer in peers:
            computer_info = ComputerInfo(
                name=peer.name,
                status="online",
                user=peer.user,
                host=peer.host,
                role=peer.role,
                system_stats=peer.system_stats,
            )
            self.cache.update_computer(computer_info)

        for peer in peers:
            try:
                self._schedule_refresh(
                    computer=peer.name,
                    data_type="projects",
                    reason="startup",
                    force=True,
                )
            except Exception as e:
                logger.warning("Failed to refresh snapshot from %s: %s", peer.name, e)

        logger.info("Remote cache snapshot refresh complete: %d computers", len(peers))

    def request_refresh(
        self,
        computer: str,
        data_type: str,
        *,
        reason: str,
        project_path: str | None = None,
        force: bool = False,
    ) -> bool:
        """Request a remote refresh if the reason is allowed and cooldown permits it."""
        return self._schedule_refresh(
            computer=computer,
            data_type=data_type,
            reason=reason,
            project_path=project_path,
            force=force,
        )

    def _schedule_refresh(
        self,
        *,
        computer: str,
        data_type: str,
        reason: str,
        project_path: str | None = None,
        force: bool = False,
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Coalesce refresh requests by peer+data type and enforce cooldown."""
        if reason not in self._ALLOWED_REFRESH_REASONS:
            logger.warning("Skipping refresh for %s:%s: reason not allowed (%s)", computer, data_type, reason)
            return False

        if computer in ("local", self.computer_name):
            return False

        key = self._refresh_key(computer, data_type, project_path)
        if not self._can_schedule_refresh(key, force=force):
            logger.debug("Refresh skipped for %s (reason=%s, force=%s)", key, reason, force)
            return False

        coro = self._build_refresh_coro(computer, data_type, project_path)
        if coro is None:
            logger.warning("Skipping refresh for %s:%s (reason=%s): unsupported data type", computer, data_type, reason)
            return False

        self._refresh_last[key] = time.monotonic()

        async def _refresh_wrapper() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Refresh failed for %s (reason=%s): %s", key, reason, exc)
            else:
                if on_success:
                    on_success()

        task = self._spawn_refresh_task(_refresh_wrapper(), key=key)
        self._refresh_tasks[key] = task
        return True

    def _refresh_key(self, computer: str, data_type: str, project_path: str | None) -> str:
        if data_type == "sessions":
            return "sessions:global"
        if project_path:
            return f"{computer}:{data_type}:{project_path}"
        return f"{computer}:{data_type}"

    def _can_schedule_refresh(self, key: str, *, force: bool) -> bool:
        task = self._refresh_tasks.get(key)
        if task and not task.done():
            return False
        if force:
            return True
        last = self._refresh_last.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._refresh_cooldown_seconds

    def _build_refresh_coro(
        self,
        computer: str,
        data_type: str,
        project_path: str | None,
    ) -> Optional[Awaitable[None]]:
        if data_type in ("projects", "preparation"):
            return self.pull_remote_projects_with_todos(computer)
        if data_type == "todos":
            if not project_path:
                return None
            return self.pull_remote_todos(computer, project_path)
        if data_type == "sessions":
            return self.pull_interested_sessions()
        return None

    def _spawn_refresh_task(self, coro: Awaitable[None], *, key: str) -> asyncio.Task[object]:
        if self.task_registry:
            task = self.task_registry.spawn(coro, name=f"redis-refresh-{key}")
        else:
            task = asyncio.create_task(coro)
            task.add_done_callback(self._log_task_exception)

        def _cleanup(_task: asyncio.Task[object]) -> None:
            self._refresh_tasks.pop(key, None)

        task.add_done_callback(_cleanup)
        return task

    async def _peer_refresh_loop(self) -> None:
        """Background task: refresh peer cache from heartbeats."""
        while self._running:
            try:
                await self.refresh_peers_from_heartbeats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Peer refresh failed: %s", e)

            # Always sleep interval, even on error, to prevent tight loops
            await asyncio.sleep(self.heartbeat_interval)

    async def refresh_peers_from_heartbeats(self) -> None:
        """Refresh peer cache from heartbeat keys."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping peer refresh from heartbeats")
            return

        redis_client = await self._get_redis()
        keys: object = await scan_keys(redis_client, b"computer:*:heartbeat")
        if not keys:
            return

        for key in keys:  # pyright: ignore[reportGeneralTypeIssues]
            try:
                data_bytes: object = await redis_client.get(key)
                data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
                info_obj: object = json.loads(data_str)
                info = cast(dict[str, object], info_obj)

                computer_name = cast(str, info["computer_name"])
                if computer_name == self.computer_name:
                    continue

                computer_info = ComputerInfo(
                    name=computer_name,
                    status="online",
                    user=cast("str | None", info.get("user")),
                    host=cast("str | None", info.get("host")),
                    role=cast("str | None", info.get("role")),
                    system_stats=cast("SystemStats | None", info.get("system_stats")),
                )
                self.cache.update_computer(computer_info)

                digest_obj = info.get("projects_digest")
                if isinstance(digest_obj, str):
                    last_digest = self._peer_digests.get(computer_name)
                    if last_digest != digest_obj:
                        logger.info("Project digest changed for %s, refreshing projects", computer_name)
                        digest_value = digest_obj
                        scheduled = self._schedule_refresh(
                            computer=computer_name,
                            data_type="projects",
                            reason="digest",
                            force=True,
                            on_success=lambda name=computer_name, d=digest_value: self._peer_digests.__setitem__(
                                name, d
                            ),
                        )
                        if not scheduled:
                            self._peer_digests[computer_name] = digest_value
            except Exception as exc:
                logger.warning("Heartbeat peer parse failed: %s", exc)
                continue

    def _create_redis_client(self) -> Redis:
        """Create a Redis client with the configured settings."""
        redis_client: Redis = Redis.from_url(
            self.redis_url,
            password=self.redis_password,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
            decode_responses=False,  # We handle decoding manually
            ssl_cert_reqs=ssl.CERT_NONE,  # Disable certificate verification for self-signed certs
        )
        return redis_client

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
                    await self.redis.aclose()
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

        if self._session_events_poll_task:
            self._session_events_poll_task.cancel()
            try:
                await self._session_events_poll_task
            except asyncio.CancelledError:
                pass

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

        logger.info("RedisTransport stopped")

    async def _get_last_processed_message_id(self) -> Optional[str]:
        """Get last processed Redis message ID from database.

        Returns:
            Last message ID or None if not found
        """
        try:
            key = f"redis_last_message_id:{self.computer_name}"
            return await db.get_system_setting(key)
        except Exception as e:
            logger.warning("Failed to get last processed message ID: %s", e)
            return None

    async def _set_last_processed_message_id(self, message_id: str) -> None:
        """Persist last processed Redis message ID to database.

        Args:
            message_id: Redis stream message ID
        """
        try:
            key = f"redis_last_message_id:{self.computer_name}"
            await db.set_system_setting(key, message_id)
        except Exception as e:
            logger.error("Failed to persist last processed message ID: %s", e)

    async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Redis transport does not stream session output; noop for compatibility."""
        logger.debug(
            "send_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id[:8],
        )
        return ""

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """No-op for Redis transport."""
        logger.debug(
            "edit_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id[:8],
        )
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """No-op for Redis transport."""
        logger.debug(
            "delete_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id[:8],
        )
        return True

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """No-op for Redis transport (errors surface via request/response)."""
        logger.debug(
            "send_error_feedback ignored for RedisTransport (session output streaming disabled): %s",
            session_id[:8],
        )

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send file - not supported by Redis adapter.

        Args:
            session: Session object
            file_path: Path to file
            metadata: Optional metadata
            caption: Optional caption

        Returns:
            Empty string (not supported)
        """
        logger.warning("send_file not supported by RedisTransport")
        return ""

    async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Send general message (not implemented for Redis).

        Redis adapter is session-specific, no general channel.

        Args:
            text: Message text
            metadata: Optional metadata

        Returns:
            Empty string
        """
        logger.warning("send_general_message not supported by RedisTransport")
        return ""

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        """Record transport metadata for AI-to-AI sessions (no Redis output streams)."""

        redis_meta = session.adapter_metadata.redis
        if not redis_meta:
            redis_meta = RedisTransportMetadata()
            session.adapter_metadata.redis = redis_meta

        if metadata.target_computer:
            redis_meta.target_computer = metadata.target_computer
            logger.info(
                "Recorded Redis target for AI-to-AI session %s: target=%s",
                session.session_id[:8],
                metadata.target_computer,
            )

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return ""

    async def update_channel_title(self, session: Session, title: str) -> bool:
        """Update channel title (no-op for Redis).

        Args:
            session: Session object
            title: New title

        Returns:
            True
        """
        return True

    async def close_channel(self, session: Session) -> bool:
        """No-op: Redis has no persistent channels to close.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def reopen_channel(self, session: Session) -> bool:
        """No-op: Redis has no persistent channels to reopen.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def delete_channel(self, session: Session) -> bool:
        """No-op: Redis transport does not create per-session output streams."""
        return True

    async def _get_online_computers(self) -> list[str]:
        """Get list of online computer names from Redis heartbeat keys.

        Reusable helper for discovering online computers without enriching
        with computer_info. Used by discover_peers() and session aggregation.

        Returns:
            List of computer names (excluding self). Returns empty list on error
            to allow graceful degradation when Redis is unavailable.

        Note:
            Errors are logged but do not propagate. This enables the system to
            continue operating in single-computer mode when Redis is down.
        """

        redis_client = await self._get_redis()

        try:
            # Find all heartbeat keys using non-blocking SCAN
            keys: object = await scan_keys(redis_client, b"computer:*:heartbeat")
            logger.debug("Found %d heartbeat keys", len(keys))  # pyright: ignore[reportArgumentType]

            computers = []
            for key in keys:  # pyright: ignore[reportGeneralTypeIssues]  # pyright: ignore[reportGeneralTypeIssues]
                # Get data
                data_bytes: object = await redis_client.get(key)
                if data_bytes:
                    # Redis returns bytes - decode to str for json.loads
                    data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
                    info_obj: object = json.loads(data_str)
                    if not isinstance(info_obj, dict):
                        continue
                    info: dict[str, object] = info_obj

                    computer_name: str = str(info["computer_name"])

                    # Skip self
                    if computer_name == self.computer_name:
                        continue

                    computers.append(computer_name)

            return sorted(computers)

        except Exception as e:
            logger.error("Failed to get online computers: %s", e)
            self._schedule_reconnect("get_online_computers", e)
            return []

    async def discover_peers(self) -> list[PeerInfo]:  # pylint: disable=too-many-locals
        """Discover peers via Redis heartbeat keys.

        Returns:
            List of PeerInfo instances with peer computer information. Returns
            empty list on error to allow graceful degradation when Redis is
            unavailable.

        Note:
            Errors are logged but do not propagate. This enables the system to
            continue operating in single-computer mode when Redis is down.
        """
        logger.trace(">>> discover_peers() called, self.redis=%s", "present" if self.redis else "None")

        redis_client = await self._get_redis()

        try:
            # Find all heartbeat keys using non-blocking SCAN
            keys: list[bytes] = await scan_keys(redis_client, b"computer:*:heartbeat")
            logger.trace(
                "Redis heartbeat keys discovered",
                count=len(keys),
                keys=keys,
            )

            peers = []
            for key in keys:  # pyright: ignore[reportGeneralTypeIssues]  # pyright: ignore[reportGeneralTypeIssues]
                # Get data
                data_bytes: object = await redis_client.get(key)
                if data_bytes:
                    # Redis returns bytes - decode to str for json.loads
                    data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
                    info_obj: object = json.loads(data_str)
                    if not isinstance(info_obj, dict):
                        continue
                    info: dict[str, object] = info_obj

                    last_seen_str: object = info.get("last_seen", "")
                    last_seen_dt = parse_iso_datetime(str(last_seen_str))
                    if last_seen_dt is None:
                        logger.warning(
                            "Invalid timestamp for %s, using now: %s",
                            info.get("computer_name"),
                            last_seen_str,
                        )
                        last_seen_dt = datetime.now(timezone.utc)

                    computer_name: str = str(info["computer_name"])

                    # Skip self
                    if computer_name == self.computer_name:
                        logger.trace("Skipping self heartbeat: %s", computer_name)
                        continue
                    logger.trace("Requesting computer_info from %s", computer_name)

                    # Request computer info via get_computer_info command
                    # Transport layer generates request_id from Redis message ID
                    computer_info = None
                    try:
                        message_id = await self.send_request(computer_name, "get_computer_info", MessageMetadata())

                        # Wait for response (short timeout) - use read_response for one-shot query
                        response_data = await self.client.read_response(
                            message_id, timeout=3.0, target_computer=computer_name
                        )
                        envelope_obj: object = json.loads(response_data.strip())
                        if not isinstance(envelope_obj, dict):
                            continue
                        envelope: dict[str, object] = envelope_obj

                        # Unwrap envelope response
                        status: object = envelope.get("status")
                        if status == "error":
                            error_msg: object = envelope.get("error")
                            logger.warning("Computer %s returned error: %s", computer_name, error_msg)
                            if "Unknown redis command: get_computer_info" in str(error_msg):
                                peers.append(
                                    PeerInfo(
                                        name=computer_name,
                                        status="online",
                                        last_seen=last_seen_dt,
                                        adapter_type="redis",
                                    )
                                )
                            continue

                        # Extract data from success envelope
                        computer_info = envelope.get("data")
                        if not computer_info or not isinstance(computer_info, dict):
                            logger.warning("Invalid response data from %s: %s", computer_name, type(computer_info))
                            continue

                        logger.debug("Redis response accepted", target=computer_name, request_id=message_id[:15])

                    except (TimeoutError, Exception) as e:
                        logger.warning("Failed to get info from %s: %s", computer_name, e)
                        continue  # Skip this peer if request fails

                    # Extract peer info with type conversions
                    user_val: object = computer_info.get("user")
                    host_val: object = computer_info.get("host")
                    ip_val: object = computer_info.get("ip")
                    role_val: object = computer_info.get("role")
                    system_stats_val: object = computer_info.get("system_stats")
                    tmux_binary_val: object = computer_info.get("tmux_binary")

                    # Ensure system_stats is a dict or None, then cast to SystemStats
                    system_stats: SystemStats | None = None
                    if isinstance(system_stats_val, dict):
                        system_stats = cast(SystemStats, system_stats_val)

                    peers.append(
                        PeerInfo(
                            name=computer_name,
                            status="online",
                            last_seen=last_seen_dt,
                            adapter_type="redis",
                            user=str(user_val) if user_val else None,
                            host=str(host_val) if host_val else None,
                            ip=str(ip_val) if ip_val else None,
                            role=str(role_val) if role_val else None,
                            system_stats=system_stats,
                            tmux_binary=str(tmux_binary_val) if tmux_binary_val else None,
                        )
                    )

            return sorted(peers, key=lambda p: p.name)

        except Exception as e:
            logger.error("Failed to discover peers: %s", e)
            self._schedule_reconnect("discover_peers", e)
            return []

    def get_max_message_length(self) -> int:
        """Get max message length for Redis (unlimited, but use 4KB for safety).

        Returns:
            4096 characters
        """
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        """Get polling interval for AI sessions.

        Returns:
            0.5 seconds (fast polling for real-time AI communication)
        """
        return 0.5

    async def _poll_redis_messages(self) -> None:
        """Background task: Poll messages:{computer_name} stream for incoming messages."""

        message_stream = f"messages:{self.computer_name}"
        self._reset_idle_poll_log_throttle()

        # Load last processed message ID from database (prevents re-processing on restart)
        last_id_str = await self._get_last_processed_message_id()
        if last_id_str:
            last_id = last_id_str.encode("utf-8")
            logger.info("Starting Redis message polling: %s (resuming from last_id=%s)", message_stream, last_id_str)
        else:
            # First startup - use current time to avoid processing old messages
            last_id = b"$"  # $ means "latest" in Redis
            logger.info("Starting Redis message polling: %s (from current time - first startup)", message_stream)

        while self._running:
            try:
                # Read messages from stream (blocking)
                # logger.debug(
                #     "About to XREAD from %s with last_id=%s, block=1000ms",
                #     message_stream,
                #     last_id,
                # )

                redis_client = await self._get_redis()
                messages: list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]] = await redis_client.xread(
                    {message_stream.encode("utf-8"): last_id},
                    block=1000,  # Block for 1 second
                    count=5,
                )

                # logger.debug(
                #     "XREAD returned %d stream(s) with messages",
                #     len(messages) if messages else 0,
                # )

                if not messages:
                    self._maybe_log_idle_poll(message_stream=message_stream)
                    continue

                self._reset_idle_poll_log_throttle()

                # Process commands
                for (
                    stream_name,
                    stream_messages,
                ) in messages:
                    stream_name_str: str = stream_name.decode("utf-8")
                    logger.debug(
                        "Stream %s has %d message(s)",
                        stream_name_str,
                        len(stream_messages),
                    )

                    for message_id, data in stream_messages:
                        logger.debug(
                            "Processing message %s with data keys: %s",
                            message_id.decode("utf-8"),
                            [k.decode("utf-8") for k in data.keys()],
                        )

                        # Persist last_id BEFORE processing to prevent re-processing on restart
                        # This is critical for deploy commands that call os._exit(0)
                        last_id = message_id
                        msg_id_str: str = last_id.decode("utf-8")
                        await self._set_last_processed_message_id(msg_id_str)
                        logger.debug("Saved last_id %s before processing", msg_id_str)

                        # Process message with Redis message_id for response correlation
                        await self._handle_incoming_message(msg_id_str, data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await self._handle_redis_error("Message polling error", e)

    async def _handle_incoming_message(self, message_id: str, data: dict[bytes, bytes]) -> Any:
        """Handle incoming message from Redis stream.

        Args:
            message_id: Redis stream entry ID (used for response correlation via output:{computer}:{message_id})
            data: Message data dict from Redis stream
        """
        try:
            parsed = self._parse_redis_message(data)

            if parsed.msg_type == "system":
                return await self._handle_system_message(data)

            if not parsed.command:
                logger.warning("Invalid message data: %s", data)
                return

            cmd_name, cmd_args = parse_command_string(parsed.command)
            if cmd_name in {"stop_notification", "input_notification"}:
                result = await self._handle_agent_notification_command(cmd_name, cmd_args)
                response_json = json.dumps(result)
                await self.send_response(message_id, response_json)
                return
            if cmd_name in {"list_sessions", "list_projects", "list_projects_with_todos", "get_computer_info"}:
                from teleclaude.core import command_handlers

                if cmd_name == "list_sessions":
                    payload = [summary.to_dict() for summary in await command_handlers.list_sessions()]
                elif cmd_name == "list_projects":
                    payload = [project.to_dict() for project in await command_handlers.list_projects()]
                elif cmd_name == "list_projects_with_todos":
                    payload = [project.to_dict() for project in await command_handlers.list_projects_with_todos()]
                else:
                    payload = (await command_handlers.get_computer_info()).to_dict()

                response_json = json.dumps({"status": "success", "data": payload})
                await self.send_response(message_id, response_json)
                return

            # Normalize via mapper
            command = CommandMapper.map_redis_input(
                command_str=parsed.command,
                session_id=parsed.session_id,
                project_path=parsed.project_path,
                title=parsed.title,
                channel_metadata=parsed.channel_metadata,
                launch_intent=parsed.launch_intent,
                origin=parsed.origin,
            )
            command.request_id = message_id

            launch_intent_obj = None
            if isinstance(parsed.launch_intent, dict):
                launch_intent_obj = SessionLaunchIntent.from_dict(parsed.launch_intent)
            metadata = MessageMetadata(
                channel_metadata=parsed.channel_metadata,
                project_path=parsed.project_path,
                title=parsed.title,
                launch_intent=launch_intent_obj,
            )

            if parsed.initiator:
                # Ensure target_computer set for stop forwarding
                metadata.channel_metadata = metadata.channel_metadata or {}
                metadata.channel_metadata["target_computer"] = parsed.initiator

            logger.info(">>> About to call command service for: %s", command.command_type)
            result = await self._execute_command(command)
            logger.info(">>> command service completed for: %s", command.command_type)

            # Result is always envelope: {"status": "success/error", "data": ..., "error": ...}
            response_json = json.dumps(result)
            logger.info(
                ">>> About to send_response for message_id: %s, response length: %d", message_id[:8], len(response_json)
            )
            await self.send_response(message_id, response_json)
            logger.info(">>> send_response completed for message_id: %s", message_id[:8])

        except Exception as e:
            logger.error("Failed to handle incoming message: %s", e, exc_info=True)
            # Send error response if possible
            try:
                error_response = json.dumps({"status": "error", "error": str(e)})
                await self.send_response(message_id, error_response)
            except Exception:
                pass

    async def _handle_agent_notification_command(self, cmd_name: str, args: list[str]) -> dict[str, object]:
        """Handle stop_notification/input_notification commands as agent_event payloads."""
        if cmd_name == "stop_notification":
            if len(args) < 2:
                logger.warning(
                    "stop_notification requires at least 2 args (session_id, source_computer), got %d", len(args)
                )
                return {"status": "error", "error": "invalid stop_notification args"}

            target_session_id = args[0]
            source_computer = args[1]
            title_b64 = args[2] if len(args) > 2 else None
            resolved_title = None

            if title_b64:
                try:
                    resolved_title = base64.b64decode(title_b64).decode()
                except Exception as e:
                    logger.warning("Failed to decode stop_notification title: %s", e)

            event_data: dict[str, object] = {
                "session_id": target_session_id,
                "source_computer": source_computer,
            }
            if resolved_title:
                event_data["title"] = resolved_title

            context = AgentEventContext(
                session_id=target_session_id,
                event_type=AgentHookEvents.AGENT_STOP,
                data=build_agent_payload(AgentHookEvents.AGENT_STOP, event_data),
            )
            event_bus.emit(TeleClaudeEvents.AGENT_EVENT, context)
            return {"status": "success", "data": None}

        if cmd_name == "input_notification":
            if len(args) < 3:
                logger.warning(
                    "input_notification requires 3 args (session_id, source_computer, message_b64), got %d",
                    len(args),
                )
                return {"status": "error", "error": "invalid input_notification args"}

            target_session_id = args[0]
            source_computer = args[1]
            message_b64 = args[2]
            message = ""

            try:
                message = base64.b64decode(message_b64).decode()
            except Exception as e:
                logger.warning("Failed to decode input_notification message: %s", e)

            event_data = {
                "session_id": target_session_id,
                "source_computer": source_computer,
                "message": message,
            }
            context = AgentEventContext(
                session_id=target_session_id,
                event_type=AgentHookEvents.AGENT_NOTIFICATION,
                data=build_agent_payload(AgentHookEvents.AGENT_NOTIFICATION, event_data),
            )
            event_bus.emit(TeleClaudeEvents.AGENT_EVENT, context)
            return {"status": "success", "data": None}

        return {"status": "error", "error": f"unsupported agent notification: {cmd_name}"}

    async def _execute_command(self, command: object) -> dict[str, object]:
        """Execute a command via command service and return an envelope."""
        try:
            cmds = get_command_service()
            if isinstance(command, CreateSessionCommand):
                data = await cmds.create_session(command)
                return {"status": "success", "data": data}
            if isinstance(command, ProcessMessageCommand):
                await cmds.process_message(command)
                return {"status": "success", "data": None}
            if isinstance(command, KeysCommand):
                await cmds.keys(command)
                return {"status": "success", "data": None}
            if isinstance(command, StartAgentCommand):
                await cmds.start_agent(command)
                return {"status": "success", "data": None}
            if isinstance(command, ResumeAgentCommand):
                await cmds.resume_agent(command)
                return {"status": "success", "data": None}
            if isinstance(command, RestartAgentCommand):
                await cmds.restart_agent(command)
                return {"status": "success", "data": None}
            if isinstance(command, RunAgentCommand):
                await cmds.run_agent_command(command)
                return {"status": "success", "data": None}
            if isinstance(command, GetSessionDataCommand):
                data = await cmds.get_session_data(command)
                return {"status": "success", "data": data}
            if isinstance(command, CloseSessionCommand):
                await cmds.close_session(command)
                return {"status": "success", "data": None}
            raise ValueError(f"Unsupported command type: {type(command).__name__}")
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _parse_redis_message(self, data: dict[bytes, bytes]) -> RedisInboundMessage:
        """Decode raw Redis stream entry into typed RedisInboundMessage."""
        msg_type = data.get(b"type", b"").decode("utf-8")
        session_id = data.get(b"session_id", b"").decode("utf-8") or None
        command = data.get(b"command", b"").decode("utf-8")
        origin = data.get(b"origin", b"").decode("utf-8") or InputOrigin.REDIS.value

        channel_metadata: dict[str, object] | None = None
        if b"channel_metadata" in data:
            try:
                parsed = json.loads(data[b"channel_metadata"].decode("utf-8"))
                if isinstance(parsed, dict):
                    channel_metadata = parsed
            except json.JSONDecodeError:
                logger.warning("Invalid channel_metadata JSON in message")

        initiator = data.get(b"initiator", b"").decode("utf-8") or None
        project_path = data.get(b"project_path", b"").decode("utf-8") or None
        title = data.get(b"title", b"").decode("utf-8") or None
        launch_intent_raw = data.get(b"launch_intent", b"").decode("utf-8") or None
        launch_intent = None
        if launch_intent_raw:
            try:
                parsed_intent = json.loads(launch_intent_raw)
                if isinstance(parsed_intent, dict):
                    launch_intent = cast(dict[str, object], parsed_intent)
            except json.JSONDecodeError:
                logger.warning("Invalid launch_intent JSON in message")

        return RedisInboundMessage(
            msg_type=msg_type,
            session_id=session_id,
            command=command,
            channel_metadata=channel_metadata,
            initiator=initiator,
            project_path=project_path,
            title=title,
            origin=origin,
            launch_intent=launch_intent,
        )

    async def _handle_system_message(self, data: dict[bytes, bytes]) -> None:
        """Handle incoming system message from Redis stream.

        System messages are daemon-level commands, not session-specific.

        Args:
            data: System message data dict from Redis stream
        """
        command = data.get(b"command", b"").decode("utf-8")
        from_computer = data.get(b"from_computer", b"").decode("utf-8")
        args_json = data.get(b"args", b"{}").decode("utf-8")

        if not command:
            logger.warning("Invalid system command data: %s", data)
            return

        # Parse args
        args_obj: object
        try:
            args_obj = json.loads(args_json)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in system command args: %s", args_json[:100])
            args_obj = {}

        logger.info("Received system command '%s' from %s", command, from_computer)

        verify_health = True
        if isinstance(args_obj, dict) and "verify_health" in args_obj:
            try:
                verify_health = bool(args_obj["verify_health"])
            except Exception:
                verify_health = True
        deploy_args = DeployArgs(verify_health=verify_health)

        event_bus.emit(
            "system_command",
            SystemCommandContext(
                command=command,
                from_computer=from_computer or "unknown",
                args=deploy_args,
            ),
        )

    async def _heartbeat_loop(self) -> None:
        """Background task: Send heartbeat every N seconds."""

        logger.info("Heartbeat loop started for computer: %s", self.computer_name)
        while self._running:
            try:
                await self._send_heartbeat()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                await self._handle_redis_error("Heartbeat failed", e)

    async def _send_heartbeat(self) -> None:
        """Send minimal Redis key with TTL as heartbeat (presence ping + interest advertising)."""
        logger.trace("Sent heartbeat for %s", self.computer_name)
        key = f"computer:{self.computer_name}:heartbeat"

        # Payload with interest advertising
        payload: dict[str, object] = {  # guard: loose-dict - heartbeat payload
            "computer_name": self.computer_name,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }

        # Include interest if cache available
        # Collect all data types we have interest in (across all computers)
        if self.cache:
            all_data_types: set[str] = set()
            # Check for common data types
            for data_type in ["sessions", "projects", "todos"]:
                if self.cache.get_interested_computers(data_type):
                    all_data_types.add(data_type)

            if all_data_types:
                payload["interested_in"] = list(all_data_types)
                logger.trace("Heartbeat includes interest: %s", all_data_types)

        if self.cache:
            digest = self.cache.get_projects_digest(self.computer_name)
            if digest:
                payload["projects_digest"] = digest

        # Set key with auto-expiry
        redis_client = await self._get_redis()
        await redis_client.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )

    # === Event Push (Phase 5) ===

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications and push to interested peers.

        Args:
            event: Event type from cache (e.g., "session_updated", "session_started")
            data: Event data (session info dict, etc.)
        """
        # Only push session-related events
        if event not in ("session_updated", "session_started", "session_closed"):
            return

        # Push events asynchronously without blocking cache notification
        if self.task_registry:
            task = self.task_registry.spawn(self._push_session_event_to_peers(event, data), name="redis-push-event")
        else:
            task = asyncio.create_task(self._push_session_event_to_peers(event, data))
        task.add_done_callback(
            lambda t: logger.error("Push task failed: %s", t.exception())
            if t.done() and not t.cancelled() and t.exception()
            else None
        )

    async def _push_session_event_to_peers(self, event: str, data: object) -> None:
        """Push session event to interested remote peers.

        Args:
            event: Event type ("session_updated", "session_started", or "session_closed")
            data: Session data dict
        """
        try:
            # Get interested computers
            interested = await self._get_interested_computers("sessions")
            if not interested:
                logger.trace("No peers interested in sessions, skipping event push")
                return

            # Prepare event payload
            if not isinstance(data, dict):
                logger.warning("Event data is not a dict, cannot push: %s", type(data))
                return

            payload: dict[str, object] = {  # guard: loose-dict - event payload
                "event": event,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_computer": self.computer_name,
            }

            # Push to each interested peer
            redis_client = await self._get_redis()
            for computer in interested:
                stream_key = f"session_events:{computer}"
                try:
                    await redis_client.xadd(
                        stream_key.encode("utf-8"),
                        {b"payload": json.dumps(payload).encode("utf-8")},
                        maxlen=100,  # Keep last 100 events
                    )
                    logger.debug("Pushed %s event to %s", event, computer)
                except Exception as e:
                    logger.error("Failed to push event to %s: %s", computer, e)

        except Exception as e:
            logger.error("Failed to push session event: %s", e, exc_info=True)

    async def _get_interested_computers(self, interest_type: str) -> list[str]:
        """Get list of computers interested in a specific type of event.

        Args:
            interest_type: Interest type to filter by (e.g., "sessions", "preparation")

        Returns:
            List of computer names that advertised interest in this type. Returns
            empty list on error to allow graceful degradation when Redis is
            unavailable.

        Note:
            Errors are logged but do not propagate. This enables the system to
            continue operating in single-computer mode when Redis is down.
        """
        try:
            redis_client = await self._get_redis()

            # Scan all heartbeat keys using non-blocking SCAN
            keys: object = await scan_keys(redis_client, b"computer:*:heartbeat")
            if not keys:
                return []

            interested_computers = []
            for key in keys:  # pyright: ignore[reportGeneralTypeIssues]
                # Get heartbeat data
                data_bytes: object = await redis_client.get(key)
                if not data_bytes:
                    continue

                # Parse heartbeat payload
                data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
                info_obj: object = json.loads(data_str)
                if not isinstance(info_obj, dict):
                    continue
                info: dict[str, object] = info_obj

                computer_name: str = str(info["computer_name"])

                # Skip self
                if computer_name == self.computer_name:
                    continue

                # Populate cache with computer info from heartbeat
                if self.cache:
                    computer_info = ComputerInfo(
                        name=computer_name,
                        status="online",
                        user=None,
                        host=None,
                        role=None,
                        system_stats=None,
                    )
                    self.cache.update_computer(computer_info)

                # Check if computer is interested in this type
                interested_in_obj: object = info.get("interested_in", [])
                if not isinstance(interested_in_obj, list):
                    continue
                interested_in: list[object] = interested_in_obj

                if interest_type in interested_in:
                    interested_computers.append(computer_name)
                    logger.trace("Computer %s is interested in %s", computer_name, interest_type)

            return interested_computers
        except Exception as e:
            logger.error("Failed to get interested computers: %s", e)
            self._schedule_reconnect("get_interested_computers", e)
            return []

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Push local session updates to interested peers via Redis."""
        session = await db.get_session(context.session_id)
        if not session:
            return
        if session.closed_at:
            await self._push_session_event_to_peers("session_closed", {"session_id": session.session_id})
            return

        summary = SessionSummary(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            thinking_mode=session.thinking_mode or ThinkingMode.SLOW.value,
            active_agent=session.active_agent,
            status="active",
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            last_input=session.last_message_sent,
            last_input_at=session.last_message_sent_at.isoformat() if session.last_message_sent_at else None,
            last_output=get_last_feedback(session),
            last_output_at=session.last_feedback_received_at.isoformat() if session.last_feedback_received_at else None,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
        )

        await self._push_session_event_to_peers("session_updated", summary.to_dict())

    async def _handle_session_started(self, _event: str, context: SessionLifecycleContext) -> None:
        """Push local session creations to interested peers via Redis."""
        session = await db.get_session(context.session_id)
        if not session:
            return

        summary = SessionSummary(
            session_id=session.session_id,
            last_input_origin=session.last_input_origin,
            title=session.title,
            project_path=session.project_path,
            subdir=session.subdir,
            thinking_mode=session.thinking_mode or ThinkingMode.SLOW.value,
            active_agent=session.active_agent,
            status="active",
            created_at=session.created_at.isoformat() if session.created_at else None,
            last_activity=session.last_activity.isoformat() if session.last_activity else None,
            last_input=session.last_message_sent,
            last_input_at=session.last_message_sent_at.isoformat() if session.last_message_sent_at else None,
            last_output=get_last_feedback(session),
            last_output_at=session.last_feedback_received_at.isoformat() if session.last_feedback_received_at else None,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
        )

        await self._push_session_event_to_peers("session_started", summary.to_dict())

    async def _handle_session_closed(self, _event: str, context: SessionLifecycleContext) -> None:
        """Push local session removals to interested peers via Redis."""
        await self._push_session_event_to_peers("session_closed", {"session_id": context.session_id})

    async def _pull_initial_sessions(self) -> None:
        """Pull existing sessions from remote computers that have registered interest.

        This ensures remote sessions appear in TUI on startup, not just after new events.
        Only pulls from computers that the local client has explicitly subscribed to.
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping initial session pull")
            return

        logger.info("Performing initial session pull from interested computers")

        # Get computers that we have interest in for sessions
        interested_computers = self.cache.get_interested_computers("sessions")
        if not interested_computers:
            logger.debug("No interested computers for session pull")
            return

        # Get all known remote computers from cache
        all_computers = self.cache.get_computers()
        computer_map = {c.name: c for c in all_computers}

        # Pull sessions only from computers we're interested in
        for computer_name in interested_computers:
            if computer_name not in computer_map:
                logger.debug("Interested computer %s not found in heartbeats, skipping", computer_name)
                continue
            try:
                # Request sessions via Redis (calls list_sessions handler on remote)
                message_id = await self.send_request(computer_name, "list_sessions", MessageMetadata())

                # Wait for response with short timeout
                response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer_name)
                envelope_obj: object = json.loads(response_data.strip())

                if not isinstance(envelope_obj, dict):
                    logger.warning("Invalid response from %s: not a dict", computer_name)
                    continue

                envelope: dict[str, object] = envelope_obj

                # Check response status
                status = envelope.get("status")
                if status == "error":
                    error_msg = envelope.get("error", "unknown error")
                    logger.warning("Error from %s: %s", computer_name, error_msg)
                    continue

                # Extract sessions data
                data = envelope.get("data")
                if not isinstance(data, list):
                    logger.warning("Invalid sessions data from %s: %s", computer_name, type(data))
                    continue

                # Populate cache with sessions
                for session_obj in data:
                    if isinstance(session_obj, dict):
                        # Cast dict to SessionSummary for cache
                        summary = SessionSummary.from_dict(session_obj)
                        summary.computer = computer_name
                        self.cache.update_session(summary)

                logger.info("Pulled %d sessions from %s", len(data), computer_name)

            except Exception as e:
                logger.warning("Failed to pull sessions from %s: %s", computer_name, e)
                continue

    async def pull_interested_sessions(self) -> None:
        """Pull sessions for currently interested computers."""
        await self._pull_initial_sessions()

    async def pull_remote_projects(self, computer: str) -> None:
        """Pull projects from a remote computer via Redis.

        Args:
            computer: Name of the remote computer to pull projects from
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping projects pull from %s", computer)
            return

        logger.debug("Pulling projects from remote computer: %s", computer)

        try:
            # Request projects via Redis (calls list_projects handler on remote)
            message_id = await self.send_request(computer, "list_projects", MessageMetadata())

            # Wait for response with short timeout
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: dict[str, object] = envelope_obj

            # Check response status
            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
                    await self.pull_remote_projects(computer)
                return

            # Extract projects data
            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid projects data from %s: %s", computer, type(data))
                return

            # Convert to ProjectInfo list
            projects: list[ProjectInfo] = []
            for project_obj in data:
                if isinstance(project_obj, dict):
                    # Ensure computer name is set from the pull source
                    info = ProjectInfo.from_dict(project_obj)
                    info.computer = computer
                    projects.append(info)

            # Store in cache
            self.cache.apply_projects_snapshot(computer, projects)
            logger.info("Pulled %d projects from %s", len(projects), computer)

        except Exception as e:
            logger.warning("Failed to pull projects from %s: %s", computer, e)

    async def pull_remote_projects_with_todos(self, computer: str) -> None:
        """Pull projects with embedded todos from a remote computer via Redis."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping projects-with-todos pull from %s", computer)
            return

        logger.debug("Pulling projects-with-todos from %s", computer)

        try:
            message_id = await self.send_request(computer, "list_projects_with_todos", MessageMetadata())

            response_data = await self.client.read_response(message_id, timeout=5.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: dict[str, object] = envelope_obj

            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
                    await self.pull_remote_projects(computer)
                return

            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid projects-with-todos data from %s: %s", computer, type(data))
                return

            projects: list[ProjectInfo] = []
            todos_by_project: dict[str, list[TodoInfo]] = {}
            for project_obj in data:
                if not isinstance(project_obj, dict):
                    continue
                project_path = str(project_obj.get("path", ""))
                if not project_path:
                    continue
                info = ProjectInfo.from_dict(project_obj)
                info.computer = computer
                projects.append(info)
                todos_by_project[project_path] = info.todos

            self.cache.apply_projects_snapshot(computer, projects)
            self.cache.apply_todos_snapshot(computer, todos_by_project)
            logger.info("Pulled %d projects-with-todos from %s", len(projects), computer)

        except Exception as e:
            logger.warning("Failed to pull projects-with-todos from %s: %s", computer, e)

    async def pull_remote_todos(self, computer: str, project_path: str) -> None:
        """Pull todos for a specific project from a remote computer via Redis.

        Args:
            computer: Name of the remote computer
            project_path: Path to the project on the remote computer
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping todos pull from %s:%s", computer, project_path)
            return

        logger.debug("Pulling todos from %s:%s", computer, project_path)

        try:
            # Request todos via Redis (calls list_todos handler on remote)
            message_id = await self.send_request(computer, "list_todos", MessageMetadata(), args=[project_path])

            # Wait for response with short timeout
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: dict[str, object] = envelope_obj

            # Check response status
            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                return

            # Extract todos data
            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid todos data from %s: %s", computer, type(data))
                return

            # Populate cache with todos
            todos: list[TodoInfo] = []
            for todo_obj in data:
                if isinstance(todo_obj, dict):
                    todos.append(TodoInfo.from_dict(todo_obj))

            self.cache.set_todos(computer, project_path, todos)
            logger.info("Pulled %d todos from %s:%s", len(todos), computer, project_path)

        except Exception as e:
            logger.warning("Failed to pull todos from %s:%s: %s", computer, project_path, e)

    async def _poll_session_events(self) -> None:
        """Poll session events stream for incoming events from remote peers (Phase 6)."""
        stream_key = f"session_events:{self.computer_name}"
        last_id = b"$"  # Start from current position
        initial_pull_done = False

        logger.info("Starting session events polling for stream: %s", stream_key)

        while self._running:
            try:
                # Only poll if cache has interest in sessions (from any computer)
                if not self.cache or not self.cache.get_interested_computers("sessions"):
                    await asyncio.sleep(5)  # Check again in 5s
                    initial_pull_done = False  # Reset flag when interest is lost
                    continue

                # Perform initial pull when interest is first detected
                if not initial_pull_done:
                    await self._pull_initial_sessions()
                    initial_pull_done = True

                # Read from session events stream
                redis_client = await self._get_redis()
                messages = await redis_client.xread(
                    {stream_key.encode("utf-8"): last_id},
                    block=1000,
                    count=10,
                )

                if not messages:
                    continue

                # Process incoming events
                for _stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        last_id = message_id

                        # Parse event payload
                        payload_bytes: bytes = data.get(b"payload", b"")
                        if not payload_bytes:
                            continue

                        payload_str = payload_bytes.decode("utf-8")
                        payload_obj: object = json.loads(payload_str)
                        if not isinstance(payload_obj, dict):
                            continue
                        payload: dict[str, object] = payload_obj

                        # Extract event details
                        event: str = str(payload.get("event", ""))
                        event_data: object = payload.get("data")
                        source_computer: str = str(payload.get("source_computer", "unknown"))

                        if not isinstance(event_data, dict):
                            logger.warning("Event data is not a dict: %s", type(event_data))
                            continue

                        # Update cache based on event type
                        if event == "session_updated":
                            # Event data is a SessionSummary dict from remote
                            summary = SessionSummary.from_dict(event_data)
                            summary.computer = source_computer
                            self.cache.update_session(summary)
                            logger.debug("Updated cache with session from %s", source_computer)
                        elif event == "session_closed":
                            session_id: str = str(event_data.get("session_id", ""))
                            if session_id:
                                self.cache.remove_session(session_id)
                                logger.debug(
                                    "Removed session %s from cache (source: %s)", session_id[:8], source_computer
                                )

            except Exception as e:
                await self._handle_redis_error("Session events polling error", e)

        logger.info("Stopped session events polling")

    # === Session Observation (Interest Window) ===

    async def signal_observation(
        self,
        target_computer: str,
        session_id: str,
        duration_seconds: int,
    ) -> None:
        """Signal interest in observing a session on target computer.

        Creates a Redis key with TTL that tells the target computer
        to broadcast session output to Redis stream during the observation window.

        Args:
            target_computer: Computer hosting the session
            session_id: Session to observe
            duration_seconds: How long to observe (TTL for Redis key)
        """

        key = f"observation:{target_computer}:{session_id}"
        observation_data: dict[str, object] = {
            "observer": self.computer_name,
            "started_at": time.time(),
        }
        data = json.dumps(observation_data)

        # Set key with TTL - auto-expires after duration
        redis_client = await self._get_redis()
        await redis_client.setex(key, duration_seconds, data)
        logger.info(
            "Signaled observation: %s observing %s on %s for %ds",
            self.computer_name,
            session_id[:8],
            target_computer,
            duration_seconds,
        )

    async def is_session_observed(self, session_id: str) -> bool:
        """Check if any observer is watching this session.

        Args:
            session_id: Session ID to check

        Returns:
            True if someone is observing this session
        """

        key = f"observation:{self.computer_name}:{session_id}"
        redis_client = await self._get_redis()
        exists = await redis_client.exists(key)
        return bool(exists)

    # === Request/Response pattern for ephemeral queries (list_projects, etc.) ===

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: Optional[str] = None,
        args: Optional[list[str]] = None,
    ) -> str:
        """Send request to remote computer's message stream.

        Used for ephemeral queries (list_projects, etc.) and session commands.

        Args:
            computer_name: Target computer name
            command: Command to send
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Optional metadata (title, project_path for session creation)
            args: Optional command arguments (e.g., project_path for list_todos)

        Returns:
            Redis stream entry ID (used for response correlation)
        """

        message_stream = f"messages:{computer_name}"

        # Build message data
        data: dict[bytes, bytes] = {
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"initiator": self.computer_name.encode("utf-8"),
        }

        # Add session_id if provided (for session commands)
        if session_id:
            data[b"session_id"] = session_id.encode("utf-8")

        # Add command arguments if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Add optional session creation metadata
        if metadata.title:
            data[b"title"] = metadata.title.encode("utf-8")
        if metadata.project_path:
            data[b"project_path"] = metadata.project_path.encode("utf-8")
        if metadata.channel_metadata:
            data[b"channel_metadata"] = json.dumps(metadata.channel_metadata).encode("utf-8")
        if metadata.launch_intent:
            data[b"launch_intent"] = json.dumps(metadata.launch_intent.to_dict()).encode("utf-8")
        origin = metadata.origin or InputOrigin.REDIS.value
        data[b"origin"] = origin.encode("utf-8")

        # Send to Redis stream - XADD returns unique message_id
        # This message_id is used for response correlation (receiver sends response to output:{computer}:{message_id})
        redis_client = await self._get_redis()
        message_id_bytes: bytes = await redis_client.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # pyright: ignore[reportArgumentType]  # pyright: ignore[reportArgumentType]
        message_id = message_id_bytes.decode("utf-8")

        logger.trace("Redis request enqueued", stream=message_stream, message_id=message_id)
        logger.debug(
            "Redis request sent",
            target=computer_name,
            request_id=message_id[:15],
            command=command[:50],
        )
        return message_id

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request directly to Redis stream.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            message_id: Redis stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Redis stream entry ID of the response
        """

        output_stream = f"output:{self.computer_name}:{message_id}"
        logger.debug(
            "send_response() sending to stream=%s for message_id=%s (data_length=%d)",
            output_stream,
            message_id,
            len(data),
        )

        redis_client = await self._get_redis()
        response_id_bytes: bytes = await redis_client.xadd(
            output_stream,
            {
                b"chunk": data.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"message_id": message_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug(
            "send_response() completed for message_id=%s, stream=%s, response_id=%s",
            message_id,
            output_stream,
            response_id_bytes,
        )
        return response_id_bytes.decode("utf-8")

    async def read_response(self, message_id: str, timeout: float = 3.0, target_computer: str | None = None) -> str:
        """Read response from ephemeral request (non-streaming).

        Used for one-shot request/response like list_projects, get_computer_info.
        Reads once from the Redis stream instead of continuous polling.

        Args:
            message_id: Redis stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)

        Returns:
            Response data as string

        Raises:
            TimeoutError: If no response received within timeout
        """

        if target_computer:
            output_stream = f"output:{target_computer}:{message_id}"
        else:
            output_stream = f"output:{message_id}"
        start_time = time.time()
        logger.trace("Redis response wait", stream=output_stream, timeout_s=timeout)

        try:
            poll_count = 0
            while True:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(
                        "read_response() timed out after %d polls (%.1fs) for message %s",
                        poll_count,
                        elapsed,
                        message_id[:8],
                    )
                    raise TimeoutError(f"No response received for message {message_id[:8]} within {timeout}s")

                # Read from stream (blocking with 100ms timeout)
                poll_count += 1
                logger.trace(
                    "Redis response poll",
                    request_id=message_id[:8],
                    poll=poll_count,
                    elapsed_s=round(elapsed, 1),
                )
                redis_client = await self._get_redis()
                messages = await redis_client.xread({output_stream.encode("utf-8"): b"0"}, block=100, count=1)

                if messages:
                    # Got response - extract and return
                    for _stream_name, stream_messages in messages:
                        for _entry_id, data in stream_messages:
                            chunk_bytes: bytes = data.get(b"chunk", b"")
                            chunk: str = chunk_bytes.decode("utf-8")
                            if chunk:
                                logger.debug(
                                    "Redis response received",
                                    request_id=message_id[:8],
                                    polls=poll_count,
                                    length=len(chunk),
                                )
                                return chunk

                # No message yet, continue polling
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("read_response cancelled for message %s", message_id[:8])
            raise

    async def send_system_command(
        self, computer_name: str, command: str, args: Optional[dict[str, object]] = None
    ) -> str:
        """Send system command to remote computer (not session-specific).

        System commands are handled by the daemon itself, not routed to tmux.
        Examples: deploy, restart, health_check

        Args:
            computer_name: Target computer name
            command: System command (e.g., "deploy")
            args: Optional command arguments

        Returns:
            Redis stream entry ID
        """

        message_stream = f"messages:{computer_name}"

        # Build system message data
        data = {
            b"type": b"system",
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"from_computer": self.computer_name.encode("utf-8"),
            b"origin": InputOrigin.REDIS.value.encode("utf-8"),
        }

        # Add args as JSON if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Send to Redis stream
        logger.debug("Sending system command to %s: %s", computer_name, command)
        redis_client = await self._get_redis()
        message_id_bytes: bytes = await redis_client.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # pyright: ignore[reportArgumentType]  # pyright: ignore[reportArgumentType]

        logger.info("Sent system command to %s: %s", computer_name, command)
        return message_id_bytes.decode("utf-8")

    async def get_system_command_status(self, computer_name: str, command: str) -> dict[str, object]:
        """Get status of system command execution.

        Args:
            computer_name: Target computer name
            command: System command name

        Returns:
            Status dict with keys: status, timestamp, error (if failed)
        """

        status_key = f"system_status:{computer_name}:{command}"
        redis_client = await self._get_redis()
        data = await redis_client.get(status_key)

        if not data:
            return {"status": "unknown"}

        result_obj: object = json.loads(data.decode("utf-8"))
        if not isinstance(result_obj, dict):
            return {"status": "error", "error": "Invalid result format"}
        result: dict[str, object] = result_obj
        return result

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0) -> AsyncIterator[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Redis transport does not stream session output; use get_session_data polling."""
        _ = (session_id, timeout)
        raise NotImplementedError("Redis output streaming is disabled; use get_session_data polling.")
