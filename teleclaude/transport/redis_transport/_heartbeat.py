"""Heartbeat loop and cache change notification for RedisTransport."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.core import command_handlers

logger = get_logger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.cache import DaemonCache


class _HeartbeatMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: periodic heartbeat emission and cache-change no-op handler."""

    if TYPE_CHECKING:
        computer_name: str
        heartbeat_interval: int
        heartbeat_ttl: int
        _running: bool

        @property
        def cache(self) -> DaemonCache | None:
            """Return the shared daemon cache."""
            raise NotImplementedError

        async def _get_redis(self) -> Redis:
            """Return an active Redis client."""
            raise NotImplementedError

        async def _handle_redis_error(self, _context: str, _exc: Exception) -> None:
            """Schedule reconnect behavior after a Redis failure."""
            _ = (_context, _exc)
            raise NotImplementedError

    async def _heartbeat_loop(self) -> None:
        """Background task: Send heartbeat every N seconds."""

        logger.info("Heartbeat loop started for computer: %s", self.computer_name)
        while self._running:
            try:
                await self._send_heartbeat()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except (RedisError, OSError, RuntimeError, TypeError, ValueError) as e:
                await self._handle_redis_error("Heartbeat failed", e)

    async def _send_heartbeat(self) -> None:
        """Publish cross-computer identity + presence timestamp to the heartbeat key.

        The heartbeat is the cluster-wide source of identity for this computer:
        peers read it directly and never need a separate ``get_computer_info``
        round-trip. ``last_seen`` + TTL still drive presence detection.
        """
        key = f"computer:{self.computer_name}:heartbeat"

        info = await command_handlers.get_computer_info()
        payload: dict[str, object] = {  # guard: loose-dict - heartbeat payload
            "computer_name": self.computer_name,
            "last_seen": datetime.now(UTC).isoformat(),
            "user": info.user,
            "host": info.host,
            "role": info.role,
            "system_stats": info.system_stats,
        }

        # Set key with auto-expiry
        redis_client = await self._get_redis()
        await redis_client.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )
        logger.trace("Sent heartbeat for %s", self.computer_name)

    # === Event Push (Phase 5) - DISABLED ===

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications.

        Note: Push-based synchronization is DISABLED to enforce Request/Response architecture.
        This handler is now a no-op for network traffic.
        """
        _ = (event, data)
