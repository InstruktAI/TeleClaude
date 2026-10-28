"""RedisTransport: Redis Streams adapter for AI-to-AI communication.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config.machine import config
from teleclaude.constants import REDIS_REFRESH_COOLDOWN_SECONDS
from teleclaude.core.models._types import JsonDict
from teleclaude.core.protocols import RemoteExecutionProtocol

from ._adapter_noop import _AdapterNoopMixin
from ._connection import _ConnectionMixin
from ._heartbeat import _HeartbeatMixin
from ._messaging import _MessagingMixin
from ._peers import _PeersMixin
from ._pull import _PullMixin
from ._refresh import (
    DIGEST_CHANGED_REASON,
    FIRST_HEARTBEAT_REASON,
    OBSERVED_STOP_REASON,
    STARTUP_REASON,
    _RefreshMixin,
)
from ._request_response import _RequestResponseMixin

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

logger = get_logger(__name__)


class RedisTransport(  # pyright: ignore[reportIncompatibleMethodOverride]
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

    _ALLOWED_REFRESH_REASONS = {STARTUP_REASON, FIRST_HEARTBEAT_REASON, OBSERVED_STOP_REASON, DIGEST_CHANGED_REASON}

    def __init__(self, adapter_client: AdapterClient, task_registry: TaskRegistry):
        """Initialize Redis transport.

        Args:
            adapter_client: AdapterClient instance for event emission
            task_registry: TaskRegistry that tracks and supervises the transport's background tasks
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
        self._transport_runtime: SupervisedTask | None = None
        self._reconnect_task: asyncio.Task[object] | None = None
        self._running = False
        self._redis_ready = asyncio.Event()
        self._redis_last_error: str | None = None

        # Extract Redis configuration from global config
        self.redis_url = config.redis.cluster.required_url()
        self.redis_username = config.redis.cluster.username
        self.redis_password = config.redis.cluster.password
        self.computer_name = config.computer.name

        # Redis connection settings
        self.max_connections = config.redis.cluster.max_connections
        self.socket_timeout = config.redis.cluster.socket_timeout

        # Stream configuration
        self.message_stream_maxlen = config.redis.cluster.message_stream_maxlen
        self.output_stream_maxlen = config.redis.cluster.output_stream_maxlen
        self.output_stream_ttl = config.redis.cluster.output_stream_ttl

        # Heartbeat config
        self.heartbeat_interval = 30  # Send heartbeat every 30s
        self.heartbeat_ttl = 60  # Key expires after 60s

        # Track pending new_session requests for response
        self._pending_new_session_request: str | None = None

        # Track successful first-heartbeat bootstraps per peer and data type.
        self._bootstrapped: set[tuple[str, str]] = set()

        # Digest-driven projects refresh: this computer's advertised digest, and per peer the digest it
        # advertised when its projects were last pulled.
        self._local_projects_digest: str | None = None
        # The projects-with-todos answer the digest was computed from; a peer's pull is answered with it.
        self._local_projects_payload: list[JsonDict] | None = None
        self._pulled_projects_digest: dict[str, str] = {}

        # Remote refresh coalescing per peer and data type; projects, todos and preparation share one key.
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
