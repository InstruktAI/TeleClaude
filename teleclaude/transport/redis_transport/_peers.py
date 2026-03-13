"""Peer discovery for RedisTransport via Redis heartbeat keys."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.models import MessageMetadata, PeerInfo
from teleclaude.core.redis_utils import scan_keys
from teleclaude.types import SystemStats

logger = get_logger(__name__)


class _PeersMixin:
    """Mixin: online computer discovery and peer enumeration."""

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
                        last_seen_dt = datetime.now(UTC)

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
