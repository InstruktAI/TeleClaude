"""Peer discovery for RedisTransport via Redis heartbeat keys."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.models import JsonDict, MessageMetadata, PeerInfo
from teleclaude.core.redis_utils import scan_keys
from teleclaude.types import SystemStats

logger = get_logger(__name__)

_PEER_EXCEPTIONS = (
    RedisError,
    TimeoutError,
    OSError,
    RuntimeError,
    LookupError,
    ValueError,
    TypeError,
    UnicodeError,
    json.JSONDecodeError,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.adapter_client import AdapterClient


class _PeersMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: online computer discovery and peer enumeration."""

    if TYPE_CHECKING:
        client: AdapterClient
        computer_name: str
        redis: Redis

        async def _get_redis(self) -> Redis:
            """Return an active Redis client."""
            raise NotImplementedError

        def _schedule_reconnect(self, reason: str, error: Exception | None = None) -> None:
            """Schedule reconnect behavior after a Redis failure."""
            _ = (reason, error)
            raise NotImplementedError

        async def send_request(
            self,
            computer_name: str,
            command: str,
            metadata: MessageMetadata,
            session_id: str | None = None,
        ) -> str:
            """Send a request to a remote computer."""
            _ = (computer_name, command, metadata, session_id)
            raise NotImplementedError

    async def get_online_computers(self) -> list[str]:
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
                    info: JsonDict = info_obj

                    computer_name: str = str(info["computer_name"])

                    # Skip self
                    if computer_name == self.computer_name:
                        continue

                    computers.append(computer_name)

            return sorted(computers)

        except _PEER_EXCEPTIONS as e:
            logger.error("Failed to get online computers: %s", e)
            self._schedule_reconnect("get_online_computers", e)
            return []

    async def discover_peers(self) -> list[PeerInfo]:
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

            peers: list[PeerInfo] = []
            for key in keys:  # pyright: ignore[reportGeneralTypeIssues]  # pyright: ignore[reportGeneralTypeIssues]
                heartbeat = await self._load_peer_heartbeat(redis_client, key)
                if heartbeat is None:
                    continue

                computer_name, last_seen_dt = heartbeat
                if computer_name == self.computer_name:
                    logger.trace("Skipping self heartbeat: %s", computer_name)
                    continue

                peer = await self._load_peer_info(computer_name, last_seen_dt)
                if peer is not None:
                    peers.append(peer)

            return sorted(peers, key=lambda p: p.name)

        except _PEER_EXCEPTIONS as e:
            logger.error("Failed to discover peers: %s", e)
            self._schedule_reconnect("discover_peers", e)
            return []

    async def _load_peer_heartbeat(self, redis_client: Redis, key: bytes) -> tuple[str, datetime] | None:
        """Load one heartbeat entry and return its computer name and last-seen timestamp."""
        data_bytes: object = await redis_client.get(key)
        if not data_bytes:
            return None

        data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
        info_obj: object = json.loads(data_str)
        if not isinstance(info_obj, dict):
            return None

        info: JsonDict = info_obj
        computer_name = str(info["computer_name"])
        last_seen_str = info.get("last_seen", "")
        last_seen_dt = parse_iso_datetime(str(last_seen_str))
        if last_seen_dt is None:
            logger.warning("Invalid timestamp for %s, using now: %s", info.get("computer_name"), last_seen_str)
            last_seen_dt = datetime.now(UTC)

        return computer_name, last_seen_dt

    async def _load_peer_info(self, computer_name: str, last_seen_dt: datetime) -> PeerInfo | None:
        """Request detailed computer info for one peer."""
        logger.trace("Requesting computer_info from %s", computer_name)
        try:
            message_id = await self.send_request(computer_name, "get_computer_info", MessageMetadata())
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer_name)
            envelope_obj: object = json.loads(response_data.strip())
            if not isinstance(envelope_obj, dict):
                return None

            envelope: JsonDict = envelope_obj
            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error")
                logger.warning("Computer %s returned error: %s", computer_name, error_msg)
                if "Unknown redis command: get_computer_info" in str(error_msg):
                    return PeerInfo(
                        name=computer_name,
                        status="online",
                        last_seen=last_seen_dt,
                        adapter_type="redis",
                    )
                return None

            computer_info = envelope.get("data")
            if not computer_info or not isinstance(computer_info, dict):
                logger.warning("Invalid response data from %s: %s", computer_name, type(computer_info))
                return None

            logger.debug("Redis response accepted", target=computer_name, request_id=message_id[:15])
            return self._build_peer_info(computer_name, last_seen_dt, computer_info)
        except _PEER_EXCEPTIONS as e:
            logger.warning("Failed to get info from %s: %s", computer_name, e)
            return None

    def _build_peer_info(self, computer_name: str, last_seen_dt: datetime, computer_info: JsonDict) -> PeerInfo:
        """Construct a `PeerInfo` instance from a response payload."""
        system_stats_val = computer_info.get("system_stats")
        system_stats = cast(SystemStats | None, system_stats_val) if isinstance(system_stats_val, dict) else None

        return PeerInfo(
            name=computer_name,
            status="online",
            last_seen=last_seen_dt,
            adapter_type="redis",
            user=self._optional_text(computer_info.get("user")),
            host=self._optional_text(computer_info.get("host")),
            ip=self._optional_text(computer_info.get("ip")),
            role=self._optional_text(computer_info.get("role")),
            system_stats=system_stats,
            tmux_binary=self._optional_text(computer_info.get("tmux_binary")),
        )

    def _optional_text(self, value: object) -> str | None:
        """Convert a truthy value to text, otherwise return `None`."""
        return str(value) if value else None
