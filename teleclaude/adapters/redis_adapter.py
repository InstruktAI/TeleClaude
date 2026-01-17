"""Redis adapter for AI-to-AI communication via Redis Streams.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

# pylint: disable=too-many-instance-attributes

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, cast

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentHookEvents,
    EventType,
    SessionLifecycleContext,
    SessionUpdatedContext,
    TeleClaudeEvents,
    parse_command_string,
)
from teleclaude.core.models import (
    ChannelMetadata,
    CommandPayload,
    ComputerInfo,
    MessageMetadata,
    MessagePayload,
    PeerInfo,
    ProjectInfo,
    RedisAdapterMetadata,
    RedisInboundMessage,
    Session,
    SessionLaunchIntent,
    SessionSummary,
    ThinkingMode,
    TodoInfo,
)
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.core.redis_utils import scan_keys
from teleclaude.types import SystemStats

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class RedisAdapter(BaseAdapter, RemoteExecutionProtocol):  # pylint: disable=too-many-instance-attributes  # Redis adapter requires many connection and state attributes
    """Adapter for AI-to-AI communication via Redis Streams.

    Uses Redis Streams for reliable, ordered message delivery between computers.

    Implements RemoteExecutionProtocol for cross-computer orchestration.

    Architecture:
    - Each computer polls its message stream: messages:{computer_name}
    - Each session has an output stream: output:{session_id}
    - Computer registry uses Redis keys with TTL for heartbeats

    Message flow:
    - Comp1 → XADD messages:comp2 → Comp2 polls → executes message
    - Comp2 → XADD output:session_id → Comp1 polls → streams to MCP
    """

    def __init__(self, adapter_client: "AdapterClient", task_registry: "TaskRegistry | None" = None):
        """Initialize Redis adapter.

        Args:
            adapter_client: AdapterClient instance for event emission
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        super().__init__()

        # Store adapter client reference (ONLY interface to daemon)
        self.client = adapter_client
        self.client.on(TeleClaudeEvents.SESSION_UPDATED, self._handle_session_updated)
        self.client.on(TeleClaudeEvents.SESSION_CREATED, self._handle_session_created)
        self.client.on(TeleClaudeEvents.SESSION_REMOVED, self._handle_session_removed)

        # Task registry for tracked background tasks
        self.task_registry = task_registry

        # Cache reference (wired by daemon after start via property setter)
        self._cache: "DaemonCache | None" = None

        # Adapter state
        self._message_poll_task: Optional[asyncio.Task[object]] = None
        self._heartbeat_task: Optional[asyncio.Task[object]] = None
        self._session_events_poll_task: Optional[asyncio.Task[object]] = None
        self._peer_refresh_task: Optional[asyncio.Task[object]] = None
        self._connection_task: Optional[asyncio.Task[object]] = None
        self._output_stream_listeners: dict[str, asyncio.Task[object]] = {}  # session_id -> listener task
        self._running = False

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

        # Initialize redis client placeholder (actual connection established in start)
        self.redis: Redis = self._create_redis_client()

        # Idle poll logging throttling (avoid tail spam at DEBUG level)
        self._idle_poll_last_log_at: float | None = None
        self._idle_poll_suppressed: int = 0

        logger.info("RedisAdapter initialized for computer: %s", self.computer_name)

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
            logger.warning("RedisAdapter already running")
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
        logger.info("RedisAdapter start triggered (connection handled asynchronously)")

    async def _ensure_connection_and_start_tasks(self) -> None:
        """Connect and launch background tasks with retry, without blocking daemon startup."""

        await self._connect_with_backoff()

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

        logger.info("RedisAdapter connected and background tasks started")

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
                await self.pull_remote_projects_with_todos(peer.name)
            except Exception as e:
                logger.warning("Failed to refresh snapshot from %s: %s", peer.name, e)

        logger.info("Remote cache snapshot refresh complete: %d computers", len(peers))

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

        redis_client = self._require_redis()
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
                        try:
                            await self.pull_remote_projects_with_todos(computer_name)
                        except Exception as exc:
                            logger.warning(
                                "Failed to refresh projects after digest change from %s: %s",
                                computer_name,
                                exc,
                            )
                        else:
                            self._peer_digests[computer_name] = digest_obj
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

    def _require_redis(self) -> Redis:
        """Return initialized Redis client or raise for clearer errors."""
        return self.redis

    async def _connect_with_backoff(self) -> None:
        """Attempt to connect to Redis with capped exponential backoff."""

        delay = 1
        while self._running:
            try:
                self.redis = self._create_redis_client()
                await self.redis.ping()  # pyright: ignore[reportGeneralTypeIssues]
                logger.info("Redis connection successful")
                return
            except Exception as e:  # broad to keep daemon alive until Redis returns
                logger.error("Failed to connect to Redis (retry in %ss): %s", delay, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)

        logger.info("Stopped redis connection attempts (adapter no longer running)")

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect the Redis client after a connection failure."""

        delay = 1
        while self._running:
            try:
                if self.redis:
                    await self.redis.aclose()
                self.redis = self._create_redis_client()
                await self.redis.ping()  # pyright: ignore[reportGeneralTypeIssues]
                logger.info("Redis reconnection successful")
                return
            except Exception as e:  # broad to avoid crash loops
                logger.error("Redis reconnection failed (retry in %ss): %s", delay, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)

        logger.info("Stopped redis reconnection attempts (adapter no longer running)")

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

        # Cancel all output stream listeners
        for _, task in list(self._output_stream_listeners.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._output_stream_listeners.clear()

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

        logger.info("RedisAdapter stopped")

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
        """Send message chunk to Redis output stream.

        Args:
            session: Session object
            text: Message text (output chunk)
            metadata: Optional metadata (ignored for Redis)

        Returns:
            Redis stream entry ID as message_id
        """

        # Trust contract: create_channel already set up metadata
        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.channel_id:
            raise ValueError(f"Session {session.session_id} has no Redis channel_id")
        output_stream: str = redis_meta.channel_id

        # Send to Redis stream
        redis_client = self._require_redis()
        message_id_bytes: bytes = await redis_client.xadd(
            output_stream,
            {
                b"chunk": text.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"session_id": session.session_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug("Sent to Redis stream %s: %s", output_stream, message_id_bytes)
        return message_id_bytes.decode("utf-8")

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """Redis streams don't support editing - send new message instead.

        Args:
            session: Session object
            message_id: Message ID (ignored)
            text: New text
            metadata: Optional metadata

        Returns:
            True (always succeeds by sending new message)
        """
        await self.send_message(session, text, metadata=metadata)
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """Delete message from Redis stream.

        Args:
            session: Session object
            message_id: Redis stream entry ID

        Returns:
            True if successful
        """

        # Trust contract: create_channel already set up metadata
        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.output_stream:
            raise ValueError(f"Session {session.session_id} has no Redis output_stream")
        output_stream: str = redis_meta.output_stream

        try:
            redis_client = self._require_redis()
            await redis_client.xdel(output_stream, message_id)
            return True
        except Exception as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error envelope to Redis output stream.

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description
        """

        try:
            output_stream = f"output:{session_id}"
            redis_client = self._require_redis()
            await redis_client.xadd(
                output_stream,
                {
                    b"type": b"error",
                    b"error": error_message.encode("utf-8"),
                    b"timestamp": str(time.time()).encode("utf-8"),
                    b"session_id": session_id.encode("utf-8"),
                },
                maxlen=self.output_stream_maxlen,
            )
            logger.debug("Sent error to Redis stream %s: %s", output_stream, error_message)
        except Exception as e:
            logger.error("Failed to send error feedback for session %s: %s", session_id, e)

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
        logger.warning("send_file not supported by RedisAdapter")
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
        logger.warning("send_general_message not supported by RedisAdapter")
        return ""

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        """Create Redis streams for session.

        For AI-to-AI sessions (with target_computer): Creates command + output streams.
        For local sessions (no target_computer): Creates only output stream.

        Args:
            session: Session object
            title: Channel title
            metadata: Optional ChannelMetadata (may contain target_computer for AI-to-AI sessions)

        Returns:
            Output stream name as channel_id
        """

        output_stream = f"output:{session.session_id}"

        # Get or create redis metadata in adapter namespace
        redis_meta = session.adapter_metadata.redis
        if not redis_meta:
            redis_meta = RedisAdapterMetadata()
            session.adapter_metadata.redis = redis_meta

        redis_meta.channel_id = output_stream
        redis_meta.output_stream = output_stream

        # Store target computer from metadata if present
        if metadata.target_computer:
            redis_meta.target_computer = metadata.target_computer
            logger.info(
                "Created Redis streams for AI-to-AI session %s: target=%s, output=%s",
                session.session_id[:8],
                metadata.target_computer,
                output_stream,
            )
        else:
            logger.debug(
                "Created Redis output stream for local session %s: %s (no target computer)",
                session.session_id[:8],
                output_stream,
            )

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        return output_stream

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
        """Delete Redis stream.

        Args:
            session: Session object

        Returns:
            True if successful
        """

        # Trust contract: create_channel already set up metadata
        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.output_stream:
            raise ValueError(f"Session {session.session_id} has no Redis output_stream")
        output_stream: str = redis_meta.output_stream
        redis_client = self._require_redis()

        try:
            await redis_client.delete(output_stream)
            return True
        except Exception as e:
            logger.error("Failed to delete stream %s: %s", output_stream, e)
            return False

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

        redis_client = self._require_redis()

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

        redis_client = self._require_redis()

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
                    try:
                        last_seen_dt = datetime.fromisoformat(str(last_seen_str))
                    except (ValueError, TypeError) as e:
                        logger.warning("Invalid timestamp for %s, using now: %s", info.get("computer_name"), e)
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
                        response_data = await self.client.read_response(message_id, timeout=3.0)
                        envelope_obj: object = json.loads(response_data.strip())
                        if not isinstance(envelope_obj, dict):
                            continue
                        envelope: dict[str, object] = envelope_obj

                        # Unwrap envelope response
                        status: object = envelope.get("status")
                        if status == "error":
                            error_msg: object = envelope.get("error")
                            logger.warning("Computer %s returned error: %s", computer_name, error_msg)
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

                redis_client = self._require_redis()
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
                logger.error("Message polling error: %s", e)
                await self._reconnect_with_backoff()

    async def _handle_incoming_message(self, message_id: str, data: dict[bytes, bytes]) -> Any:
        """Handle incoming message from Redis stream.

        Args:
            message_id: Redis stream entry ID (used for response correlation via output:{message_id})
            data: Message data dict from Redis stream
        """
        try:
            parsed = self._parse_redis_message(data)

            if parsed.msg_type == "system":
                return await self._handle_system_message(data)

            if not parsed.command:
                logger.warning("Invalid message data: %s", data)
                return

            session_id = parsed.session_id or ""
            logger.info("Received message for session %s: %s", session_id[:8], parsed.command[:50])

            # Parse message using centralized parser FIRST
            cmd_name, args = parse_command_string(parsed.command)
            if not cmd_name:
                logger.warning("Empty message received for session %s", session_id[:8])
                return

            # Emit event to daemon via client
            event_type: EventType = cmd_name  # pyright: ignore[reportAssignmentType]  # pyright: ignore[reportAssignmentType]

            # MESSAGE and CLAUDE events use text in payload (keep message as single string)
            # Other commands use args list
            payload_obj: object
            if cmd_name == "stop_notification":
                if len(args) < 2:
                    logger.warning("stop_notification received with insufficient args: %s", args)
                    return

                target_session_id = args[0]
                source_computer = args[1]
                title: str | None = None
                if len(args) > 2:
                    try:
                        title = base64.b64decode(args[2]).decode()
                    except Exception as e:
                        logger.warning("Failed to decode title from base64: %s", e)
                        title = None

                event_type = TeleClaudeEvents.AGENT_EVENT
                event_data: dict[str, object] = {  # guard: loose-dict - Event payload assembly
                    "session_id": target_session_id,
                    "source_computer": source_computer,
                }
                if title:
                    event_data["title"] = title

                payload_obj = {
                    "session_id": target_session_id,
                    "event_type": AgentHookEvents.AGENT_STOP,
                    "data": event_data,
                }
                logger.debug("Emitting AGENT_EVENT stop for remote session %s", target_session_id[:8])
            elif cmd_name == "input_notification":
                # Format: "/input_notification {session_id} {computer} {message_b64}"
                if len(args) < 3:
                    logger.warning("input_notification received with insufficient args: %s", args)
                    return

                target_session_id = args[0]
                source_computer = args[1]
                try:
                    message = base64.b64decode(args[2]).decode()
                except Exception:
                    logger.warning("input_notification: failed to decode message")
                    return

                event_type = TeleClaudeEvents.AGENT_EVENT
                event_data = {
                    "session_id": target_session_id,
                    "source_computer": source_computer,
                    "message": message,
                }

                payload_obj = {
                    "session_id": target_session_id,
                    "event_type": AgentHookEvents.AGENT_NOTIFICATION,
                    "data": event_data,
                }
                logger.debug("Emitting AGENT_EVENT notification for remote session %s", target_session_id[:8])
            elif event_type == TeleClaudeEvents.MESSAGE:
                payload_obj = MessagePayload(session_id=session_id, text=" ".join(args) if args else "")
                logger.debug(
                    "Emitting MESSAGE event with text: %s",
                    payload_obj.text if payload_obj.text else "(empty)",
                )
            elif cmd_name in ["claude", "gemini", "codex"]:
                agent_name = cmd_name
                event_type = TeleClaudeEvents.AGENT_START
                payload_obj = CommandPayload(session_id=session_id, args=[agent_name] + args)
                logger.debug("Emitting AGENT_START event for %s with args: %s", agent_name, args)
            elif cmd_name in ["claude_resume", "gemini_resume", "codex_resume"]:
                agent_name = cmd_name.replace("_resume", "")
                event_type = TeleClaudeEvents.AGENT_RESUME
                payload_obj = CommandPayload(session_id=session_id, args=[agent_name] + args)
                logger.debug("Emitting AGENT_RESUME event for %s", agent_name)
            else:
                payload_obj = CommandPayload(session_id=session_id, args=args)
                logger.debug("Emitting %s event with args: %s", event_type, args)

            launch_intent = None
            if parsed.launch_intent:
                launch_intent = SessionLaunchIntent.from_dict(parsed.launch_intent)

            metadata_to_send = MessageMetadata(
                adapter_type="redis",
                channel_metadata=parsed.channel_metadata,
                project_path=parsed.project_path,
                title=parsed.title,
                launch_intent=launch_intent,
            )

            if parsed.initiator:
                # Ensure target_computer set for stop forwarding
                metadata_to_send.channel_metadata = metadata_to_send.channel_metadata or {}
                metadata_to_send.channel_metadata["target_computer"] = parsed.initiator

            # Enrich payload with optional project/title if supported
            if parsed.project_path and isinstance(payload_obj, (CommandPayload, MessagePayload)):
                payload_obj.project_path = parsed.project_path
            if parsed.title and isinstance(payload_obj, (CommandPayload, MessagePayload)):
                payload_obj.title = parsed.title

            logger.info(">>> About to call handle_event for event_type: %s", event_type)
            # Convert dataclass payloads to dict for handler
            if hasattr(payload_obj, "__dict__"):
                payload_dict = dict(payload_obj.__dict__)
            else:
                payload_dict = cast(dict[str, object], payload_obj)

            result = await self.client.handle_event(
                event=event_type,
                payload=payload_dict,
                metadata=metadata_to_send,
            )
            logger.info(
                ">>> handle_event completed for event_type: %s, result type: %s", event_type, type(result).__name__
            )

            # Start output stream listener for new AI-to-AI sessions
            if event_type == "new_session" and isinstance(result, dict) and result.get("status") == "success":
                result_data = result.get("data")
                if isinstance(result_data, dict):
                    new_session_id = result_data.get("session_id")
                    if new_session_id:
                        self._start_output_stream_listener(str(new_session_id))
                        logger.debug("Started output stream listener for session: %s", new_session_id)

            # Result is always envelope: {"status": "success/error", "data": ..., "error": ...}
            response_json = json.dumps(result)
            logger.info(
                ">>> About to send_response for message_id: %s, response length: %d", message_id[:8], len(response_json)
            )
            await self.send_response(message_id, response_json)
            logger.info(">>> send_response completed for message_id: %s", message_id[:8])

        except Exception as e:
            logger.error("Failed to handle incoming message: %s", e, exc_info=True)

    def _parse_redis_message(self, data: dict[bytes, bytes]) -> RedisInboundMessage:
        """Decode raw Redis stream entry into typed RedisInboundMessage."""
        msg_type = data.get(b"type", b"").decode("utf-8")
        session_id = data.get(b"session_id", b"").decode("utf-8") or None
        command = data.get(b"command", b"").decode("utf-8")

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

        # Emit SYSTEM_COMMAND event to daemon
        payload_dict: dict[str, object] = {
            "command": command,
            "args": args_obj,
            "from_computer": from_computer,
        }
        await self.client.handle_event(
            event=TeleClaudeEvents.SYSTEM_COMMAND,
            payload=payload_dict,
            metadata=MessageMetadata(),
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
                logger.error("Heartbeat failed: %s", e)
                await self._reconnect_with_backoff()

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

        payload["projects_digest"] = self._compute_projects_digest()

        # Set key with auto-expiry
        redis_client = self._require_redis()
        await redis_client.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )

    def _compute_projects_digest(self) -> str:
        """Compute a deterministic digest for local project paths."""
        trusted_dirs = config.computer.get_all_trusted_dirs()
        paths: list[str] = []

        for trusted_dir in trusted_dirs:
            raw_path = getattr(trusted_dir, "path", None)
            if not isinstance(raw_path, str):
                continue
            expanded_path = os.path.expanduser(os.path.expandvars(raw_path))
            if Path(expanded_path).exists():
                paths.append(expanded_path)

        joined = "\n".join(sorted(paths))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # === Event Push (Phase 5) ===

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications and push to interested peers.

        Args:
            event: Event type from cache (e.g., "session_updated", "session_removed")
            data: Event data (session info dict, etc.)
        """
        # Only push session-related events
        if event not in ("session_updated", "session_removed"):
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
            event: Event type ("session_updated" or "session_removed")
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
            redis_client = self._require_redis()
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
            redis_client = self._require_redis()

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
            return []

    async def _handle_session_updated(self, _event: str, context: SessionUpdatedContext) -> None:
        """Push local session updates to interested peers via Redis."""
        session = await db.get_session(context.session_id)
        if not session:
            return
        if session.closed_at:
            await self._push_session_event_to_peers("session_removed", {"session_id": session.session_id})
            return

        summary = SessionSummary(
            session_id=session.session_id,
            origin_adapter=session.origin_adapter,
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
            last_output=session.last_feedback_received,
            last_output_at=session.last_feedback_received_at.isoformat() if session.last_feedback_received_at else None,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
        )

        await self._push_session_event_to_peers("session_updated", summary.to_dict())

    async def _handle_session_created(self, _event: str, context: SessionLifecycleContext) -> None:
        """Push local session creations to interested peers via Redis."""
        session = await db.get_session(context.session_id)
        if not session:
            return

        summary = SessionSummary(
            session_id=session.session_id,
            origin_adapter=session.origin_adapter,
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
            last_output=session.last_feedback_received,
            last_output_at=session.last_feedback_received_at.isoformat() if session.last_feedback_received_at else None,
            tmux_session_name=session.tmux_session_name,
            initiator_session_id=session.initiator_session_id,
        )

        await self._push_session_event_to_peers("session_created", summary.to_dict())

    async def _handle_session_removed(self, _event: str, context: SessionLifecycleContext) -> None:
        """Push local session removals to interested peers via Redis."""
        await self._push_session_event_to_peers("session_removed", {"session_id": context.session_id})

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
                response_data = await self.client.read_response(message_id, timeout=3.0)
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
            response_data = await self.client.read_response(message_id, timeout=3.0)
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

            response_data = await self.client.read_response(message_id, timeout=5.0)
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
            response_data = await self.client.read_response(message_id, timeout=3.0)
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
                redis_client = self._require_redis()
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
                        elif event == "session_removed":
                            session_id: str = str(event_data.get("session_id", ""))
                            if session_id:
                                self.cache.remove_session(session_id)
                                logger.debug(
                                    "Removed session %s from cache (source: %s)", session_id[:8], source_computer
                                )

            except Exception as e:
                logger.error("Session events polling error: %s", e, exc_info=True)
                await asyncio.sleep(5)  # Back off on error

        logger.info("Stopped session events polling")

    # === AI-to-AI Session Output Stream Listeners ===

    def _start_output_stream_listener(self, session_id: str) -> None:
        """Start background task to poll output stream for incoming messages from initiator.

        Args:
            session_id: Session ID to listen for
        """
        if session_id in self._output_stream_listeners:
            logger.warning("Output stream listener already running for session %s", session_id[:8])
            return

        if self.task_registry:
            task = self.task_registry.spawn(
                self._poll_output_stream_for_messages(session_id), name=f"redis-output-{session_id[:8]}"
            )
        else:
            task = asyncio.create_task(self._poll_output_stream_for_messages(session_id))
            task.add_done_callback(self._log_task_exception)
        self._output_stream_listeners[session_id] = task
        logger.info("Started output stream listener for AI-to-AI session %s", session_id[:8])

    async def _poll_output_stream_for_messages(self, session_id: str) -> None:
        """Poll output stream for incoming messages from session initiator.

        This enables bidirectional communication in AI-to-AI sessions where
        the output stream is shared between initiator and remote.

        Args:
            session_id: Session ID to poll
        """

        output_stream = f"output:{session_id}"
        last_id = b"$"  # Start from current position
        logger.info("Starting output stream message polling for session %s", session_id[:8])

        try:
            while self._running:
                # Check if session still exists
                session = await db.get_session(session_id)
                if not session:
                    logger.info("Session %s missing, stopping output stream listener", session_id[:8])
                    break

                # Read from output stream
                redis_client = self._require_redis()
                messages = await redis_client.xread({output_stream.encode("utf-8"): last_id}, block=1000, count=5)

                if not messages:
                    continue

                # Process incoming messages from initiator
                for _stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        last_id = message_id

                        # Check if this is a message FROM the initiator (not our own output)
                        chunk_bytes: bytes = data.get(b"chunk", b"")
                        chunk = chunk_bytes.decode("utf-8")

                        if not chunk:
                            continue

                        # Skip system messages
                        if chunk.startswith("[") or "⏳" in chunk:
                            continue

                        # This is a message from the initiator - trigger MESSAGE event
                        logger.info("Received message from initiator for session %s: %s", session_id[:8], chunk[:50])
                        message_payload: dict[str, object] = {"session_id": session_id, "text": chunk.strip()}
                        await self.client.handle_event(
                            event=TeleClaudeEvents.MESSAGE,
                            payload=message_payload,
                            metadata=MessageMetadata(),
                        )

        except asyncio.CancelledError:
            logger.debug("Output stream listener cancelled for session %s", session_id[:8])
        except Exception as e:
            logger.error("Output stream listener error for session %s: %s", session_id[:8], e)
            await self._reconnect_with_backoff()
        finally:
            # Cleanup
            if session_id in self._output_stream_listeners:
                del self._output_stream_listeners[session_id]
            logger.info("Stopped output stream listener for session %s", session_id[:8])

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
        redis_client = self._require_redis()
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
        redis_client = self._require_redis()
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

        # Send to Redis stream - XADD returns unique message_id
        # This message_id is used for response correlation (receiver sends response to output:{message_id})
        redis_client = self._require_redis()
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

        output_stream = f"output:{message_id}"
        logger.debug(
            "send_response() sending to stream=%s for message_id=%s (data_length=%d)",
            output_stream,
            message_id,
            len(data),
        )

        redis_client = self._require_redis()
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

    async def read_response(self, message_id: str, timeout: float = 3.0) -> str:
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
                redis_client = self._require_redis()
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
        }

        # Add args as JSON if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Send to Redis stream
        logger.debug("Sending system command to %s: %s", computer_name, command)
        redis_client = self._require_redis()
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
        redis_client = self._require_redis()
        data = await redis_client.get(status_key)

        if not data:
            return {"status": "unknown"}

        result_obj: object = json.loads(data.decode("utf-8"))
        if not isinstance(result_obj, dict):
            return {"status": "error", "error": "Invalid result format"}
        result: dict[str, object] = result_obj
        return result

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0) -> AsyncIterator[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Poll output stream and yield chunks as they arrive.

        Used by MCP server to stream output from remote sessions.

        Args:
            session_id: Session ID
            timeout: Max seconds to wait for output

        Yields:
            Output chunks as they arrive
        """

        output_stream = f"output:{session_id}"
        last_id = b"$"  # Start from current position (only read new chunks)
        start_time = time.time()
        last_yield_time = time.time()
        idle_count = 0
        max_idle_polls = 120  # 120 * 0.5s = 60s max idle
        heartbeat_interval = 60  # Send heartbeat every 60s if no output

        logger.info("Starting output stream poll for session %s", session_id[:8])

        try:
            while True:
                # Check overall timeout
                if time.time() - start_time > timeout:
                    yield "\n[Timeout: Session exceeded time limit]"
                    return

                # Read from stream (blocking with 500ms timeout)
                try:
                    redis_client = self._require_redis()
                    messages = await redis_client.xread({output_stream.encode("utf-8"): last_id}, block=500, count=10)

                    if not messages:
                        # No messages - increment idle counter
                        idle_count += 1

                        # Send heartbeat if no output for a while
                        if time.time() - last_yield_time > heartbeat_interval:
                            yield "[⏳ Waiting for response...]\n"
                            last_yield_time = time.time()

                        # Timeout if idle too long
                        if idle_count >= max_idle_polls:
                            yield "\n[Timeout: No response for 60 seconds]"
                            return

                        continue

                    # Got messages - reset idle counter
                    idle_count = 0

                    # Process messages
                    for _stream_name, stream_messages in messages:
                        for message_id, data in stream_messages:
                            chunk = data.get(b"chunk", b"").decode("utf-8")

                            if not chunk:
                                continue

                            # Check for completion marker
                            if "[Output Complete]" in chunk:
                                logger.info("Received completion marker for session %s", session_id[:8])
                                return

                            # Yield chunk content
                            content = self._extract_chunk_content(chunk)
                            if content:
                                yield content
                                last_yield_time = time.time()

                            # Update last ID
                            last_id = message_id

                except Exception as e:
                    logger.error("Error polling output stream: %s", e)
                    await self._reconnect_with_backoff()

        except asyncio.CancelledError:
            logger.info("Output stream polling cancelled for session %s", session_id[:8])
            raise

    def _extract_chunk_content(self, chunk_text: str) -> str:
        """Extract actual output from chunk message.

        Strips markdown code fences and chunk markers.

        Args:
            chunk_text: Raw chunk text from Redis

        Returns:
            Extracted content without formatting
        """
        if not chunk_text:
            return ""

        # Remove markdown code fences
        content = chunk_text.replace("```sh", "").replace("```", "")
        # Remove chunk markers
        content = re.sub(r"\[Chunk \d+/\d+\]", "", content)
        return content.strip()
