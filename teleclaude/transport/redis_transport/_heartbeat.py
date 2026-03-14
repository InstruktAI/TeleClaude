"""Heartbeat loop and cache change notification for RedisTransport."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

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
        def cache(self) -> DaemonCache | None: ...

        async def _get_redis(self) -> Redis: ...
        async def _handle_redis_error(self, context: str, exc: Exception) -> None: ...

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
            "last_seen": datetime.now(UTC).isoformat(),
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

    # === Event Push (Phase 5) - DISABLED ===

    def _on_cache_change(self, event: str, data: object) -> None:
        """Handle cache change notifications.

        Note: Push-based synchronization is DISABLED to enforce Request/Response architecture.
        This handler is now a no-op for network traffic.
        """
        pass
