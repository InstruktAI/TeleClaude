"""RedisTransport: Redis Streams adapter for AI-to-AI communication.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

# pylint: disable=too-many-instance-attributes

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.constants import REDIS_REFRESH_COOLDOWN_SECONDS
from teleclaude.core.protocols import RemoteExecutionProtocol

from ._adapter_noop import _AdapterNoopMixin
from ._connection import _ConnectionMixin
from ._heartbeat import _HeartbeatMixin
from ._messaging import _MessagingMixin
from ._peers import _PeersMixin
from ._pull import _PullMixin
from ._refresh import _RefreshMixin
from ._request_response import _RequestResponseMixin

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


class RedisTransport(  # pylint: disable=too-many-instance-attributes  # Redis transport requires many connection and state attributes
    _ConnectionMixin,
    _RefreshMixin,
    _MessagingMixin,
    _HeartbeatMixin,
    _PullMixin,
    _PeersMixin,
    _RequestResponseMixin,
    _AdapterNoopMixin,
    BaseAdapter,
    RemoteExecutionProtocol,
):
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

    def store_channel_id(self, adapter_metadata: object, channel_id: str) -> None:
        """Store Redis channel_id into session adapter metadata."""
        from teleclaude.core.models import SessionAdapterMetadata  # pylint: disable=C0415

        if not isinstance(adapter_metadata, SessionAdapterMetadata):
            return

        redis_meta = adapter_metadata.get_transport().get_redis()
        redis_meta.channel_id = channel_id

    def __init__(self, adapter_client: AdapterClient, task_registry: TaskRegistry | None = None):
        """Initialize Redis transport.

        Args:
            adapter_client: AdapterClient instance for event emission
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        super().__init__()

        # Store client reference (ONLY interface to daemon)
        self.client = adapter_client
        # Note: Session event bus subscriptions removed to enforce Pull-Only architecture.
        # We no longer push session updates to Redis streams.

        # Task registry for tracked background tasks
        self.task_registry = task_registry

        # Cache reference (wired by daemon after start via property setter)
        self._cache: DaemonCache | None = None

        # Transport state
        self._message_poll_task: asyncio.Task[object] | None = None
        self._heartbeat_task: asyncio.Task[object] | None = None
        self._peer_refresh_task: asyncio.Task[object] | None = None
        self._connection_task: asyncio.Task[object] | None = None
        self._reconnect_task: asyncio.Task[object] | None = None
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
        self._pending_new_session_request: str | None = None

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
    def cache(self) -> DaemonCache | None:
        """Get cache reference."""
        return self._cache

    @cache.setter
    def cache(self, value: DaemonCache | None) -> None:
        """Set cache reference and subscribe to changes."""
        if self._cache:
            self._cache.unsubscribe(self._on_cache_change)
        self._cache = value
        if value:
            value.subscribe(self._on_cache_change)
            logger.info("Redis adapter subscribed to cache notifications")

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
