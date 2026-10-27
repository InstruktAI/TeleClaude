"""Heartbeat loop and cache change notification for RedisTransport."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.constants import CacheEvent
from teleclaude.core import command_handlers
from teleclaude.transport.peer_heartbeat import (
    CONVERSATION_ADAPTERS_FIELD,
    PROJECTS_DIGEST_FIELD,
    heartbeat_key,
    projects_digest,
)

logger = get_logger(__name__)

# Failure families the loop hands to ``_handle_redis_error`` (reconnect behavior).
_HEARTBEAT_RECOVERABLE_ERRORS = (RedisError, OSError, RuntimeError, TypeError, ValueError)
_HEARTBEAT_SAMPLE_FAILED_EVENT = "heartbeat_sample_failed"
_PROJECTS_DIGEST_FAILED_EVENT = "projects_digest_failed"
_COMPUTER_FIELD = "computer"
_PEER_INVALIDATION_EVENTS = frozenset({CacheEvent.TODOS_UPDATED.value, CacheEvent.PROJECTS_UPDATED.value})

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import PeerInfo


class _HeartbeatMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: periodic heartbeat emission and cache-change no-op handler."""

    if TYPE_CHECKING:
        computer_name: str
        heartbeat_interval: int
        heartbeat_ttl: int
        _running: bool
        _local_projects_digest: str | None
        _pulled_projects_digest: dict[str, str]

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

        async def discover_peers(self) -> list[PeerInfo]:
            """Return every live peer from its heartbeat."""
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
            except _HEARTBEAT_RECOVERABLE_ERRORS as e:
                await self._handle_redis_error("Heartbeat failed", e)

    async def _projects_digest_loop(self) -> None:
        """Background task: keep the digest of the projects-with-todos answer that peers would pull current.

        It runs apart from the heartbeat because building the answer can take longer than a heartbeat may wait.
        """
        while self._running:
            try:
                payload = [project.to_dict() for project in await command_handlers.list_projects_with_todos()]
                self._local_projects_digest = projects_digest(payload)
            except asyncio.CancelledError:
                break
            except Exception:
                # An unreadable local state leaves the last digest in place; the next pass tries again.
                logger.exception(_PROJECTS_DIGEST_FAILED_EVENT, computer_name=self.computer_name)
            await asyncio.sleep(self.heartbeat_interval)

    async def _send_heartbeat(self) -> None:
        """Publish cross-computer identity + presence timestamp to the heartbeat key.

        The heartbeat is the cluster-wide source of identity for this computer:
        peers read it directly and never need a separate ``get_computer_info``
        round-trip. ``last_seen`` + TTL still drive presence detection.
        """
        key = heartbeat_key(self.computer_name)

        try:
            info = await command_handlers.get_computer_info()
            payload: dict[str, object] = {  # guard: loose-dict - heartbeat payload
                "computer_name": self.computer_name,
                "last_seen": datetime.now(UTC).isoformat(),
                "user": info.user,
                "host": info.host,
                "role": info.role,
                "system_stats": info.system_stats,
                "version": info.version,
                "channel": info.channel,
                "capability_set": info.capability_set,
                "is_master": info.is_master,
                CONVERSATION_ADAPTERS_FIELD: info.conversation_adapters,
            }
            if self._local_projects_digest is not None:
                payload[PROJECTS_DIGEST_FIELD] = self._local_projects_digest
        except _HEARTBEAT_RECOVERABLE_ERRORS:
            raise
        except Exception:
            # An unrecognized sampling failure skips this beat; the loop paces the next one.
            logger.exception(_HEARTBEAT_SAMPLE_FAILED_EVENT, computer_name=self.computer_name)
            return

        # Set key with auto-expiry
        redis_client = await self._get_redis()
        await redis_client.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )
        logger.trace("Sent heartbeat for %s", self.computer_name)

    def _on_cache_change(self, event: str, data: object) -> None:
        """Forget the pulled digest of a peer whose cached projects or todos were invalidated.

        The next heartbeat then finds the peer's digest unequal to none recorded and pulls once, which refills
        what the invalidation dropped. Nothing is sent from here.
        """
        if event not in _PEER_INVALIDATION_EVENTS or not isinstance(data, dict):
            return
        computer = data.get(_COMPUTER_FIELD)
        if isinstance(computer, str) and computer != self.computer_name:
            self._pulled_projects_digest.pop(computer, None)
