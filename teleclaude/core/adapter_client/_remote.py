"""Remote execution and peer discovery methods for AdapterClient."""

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.models import MessageMetadata
from teleclaude.core.protocols import RemoteExecutionProtocol

if TYPE_CHECKING:
    from teleclaude.adapters.base_adapter import BaseAdapter

logger = get_logger(__name__)


class _RemoteMixin:
    """Remote execution (Redis transport) and peer discovery operations."""

    if TYPE_CHECKING:
        adapters: dict[str, "BaseAdapter"]

    async def discover_peers(
        self, redis_enabled: bool | None = None
    ) -> list[dict[str, object]]:  # guard: loose-dict - Adapter peer data
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Args:
            redis_enabled: Whether Redis is enabled. Defaults to config.redis.enabled.

        Returns:
            List of peer dicts (converted from PeerInfo dataclass) with:
            - name: Computer name
            - status: "online" or "offline"
            - last_seen: datetime object
            - last_seen_ago: Human-readable string (e.g., "30s ago")
            - adapter_type: Which adapter discovered this peer
            - user: Username (optional)
            - host: Hostname (optional)
            - ip: IP address (optional)
        """
        from typing import cast

        logger.debug("AdapterClient.discover_peers() called, adapters: %s", list(self.adapters.keys()))

        # Determine Redis enabled state - explicit param takes precedence over config
        is_redis_enabled = redis_enabled if redis_enabled is not None else config.redis.enabled

        # Early return if Redis is disabled - no peer discovery without Redis
        if not is_redis_enabled:
            logger.debug("Redis disabled, skipping peer discovery")
            return []

        all_peers: list[dict[str, object]] = []  # guard: loose-dict - Adapter peer data

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            logger.debug("Calling discover_peers() on %s adapter", adapter_type)
            try:
                peers = await adapter.discover_peers()  # Returns list[PeerInfo]
                # Convert PeerInfo dataclass to dict for transport
                for peer_info in peers:
                    peer_dict: dict[str, object] = {  # guard: loose-dict - Adapter peer data
                        "name": peer_info.name,
                        "status": peer_info.status,
                        "last_seen": peer_info.last_seen,
                        "adapter_type": peer_info.adapter_type,
                    }
                    if peer_info.user:
                        peer_dict["user"] = peer_info.user
                    if peer_info.host:
                        peer_dict["host"] = peer_info.host
                    if peer_info.ip:
                        peer_dict["ip"] = peer_info.ip
                    if peer_info.role:
                        peer_dict["role"] = peer_info.role
                    if peer_info.system_stats:
                        peer_dict["system_stats"] = peer_info.system_stats
                    if peer_info.tmux_binary:
                        peer_dict["tmux_binary"] = peer_info.tmux_binary
                    all_peers.append(peer_dict)
                logger.debug("Discovered %d peers from %s adapter", len(peers), adapter_type)
            except Exception as e:
                logger.error("Failed to discover peers from %s: %s", adapter_type, e)

        # Deduplicate by name (keep first occurrence = primary adapter wins)
        seen: set[str] = set()
        unique_peers: list[dict[str, object]] = []  # guard: loose-dict - Adapter peer data
        for peer in all_peers:
            peer_name = cast(str, peer.get("name"))
            if peer_name and peer_name not in seen:
                seen.add(peer_name)
                unique_peers.append(peer)

        logger.debug("Total discovered peers (deduplicated): %d", len(unique_peers))
        return unique_peers

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> str:
        """Send request to remote computer via transport adapter.

        Transport layer generates request_id from Redis for correlation.

        Args:
            computer_name: Target computer identifier
            command: Command to send to remote computer
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Optional metadata (title, project_path for session creation)

        Returns:
            Redis message ID (for response correlation via read_response)

        Raises:
            RuntimeError: If no transport adapter available
        """
        transport = self._get_transport_adapter()
        return await transport.send_request(computer_name, command, metadata, session_id)

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            message_id: Stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Stream entry ID of the response

        Raises:
            RuntimeError: If no transport adapter available
        """
        transport = self._get_transport_adapter()
        return await transport.send_response(message_id, data)

    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        """Read single response from request (for ephemeral request/response).

        Used for one-shot requests like list_projects, get_computer_info.
        Reads the response in one go instead of streaming.

        Args:
            message_id: Stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)
            target_computer: Optional target computer for namespaced response stream

        Returns:
            Response data as string

        Raises:
            RuntimeError: If no transport adapter available
            TimeoutError: If no response received within timeout
        """
        transport = self._get_transport_adapter()
        return await transport.read_response(message_id, timeout, target_computer)

    def _get_transport_adapter(self) -> RemoteExecutionProtocol:
        """Get first adapter that supports remote execution.

        Returns:
            Adapter implementing RemoteExecutionProtocol

        Raises:
            RuntimeError: If no transport adapter available
        """
        for adapter in self.adapters.values():
            if isinstance(adapter, RemoteExecutionProtocol):
                return adapter

        raise RuntimeError("No transport adapter available for remote execution")
