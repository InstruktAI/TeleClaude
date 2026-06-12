"""Remote execution and peer discovery methods for AdapterClient."""

import json
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict, JsonValue, MessageMetadata
from teleclaude.core.protocols import RemoteExecutionProtocol

if TYPE_CHECKING:
    from teleclaude.adapters.base_adapter import BaseAdapter
    from teleclaude.transport.redis_transport import RedisTransport

logger = get_logger(__name__)


class RemoteDispatchError(RuntimeError):
    """Raised when a peer returns an error or malformed response envelope."""


def _parse_remote_dispatch_data(
    envelope_text: str,
    *,
    target_computer: str,
    command: str,
) -> JsonValue:
    try:
        envelope_obj: object = json.loads(envelope_text)
    except json.JSONDecodeError as exc:
        raise RemoteDispatchError(f"Remote command {command} returned invalid JSON") from exc

    if not isinstance(envelope_obj, dict):
        raise RemoteDispatchError(f"Remote command {command} returned invalid response")

    envelope = cast(JsonDict, envelope_obj)
    status = envelope.get("status")
    if status == "error":
        error = envelope.get("error")
        detail = str(error) if error else f"Remote command {command} failed on {target_computer}"
        raise RemoteDispatchError(detail)
    if status != "success":
        raise RemoteDispatchError(f"Remote command {command} returned invalid status")

    return envelope.get("data")


class _RemoteMixin:  # pyright: ignore[reportUnusedClass]
    """Remote execution (Redis transport) and peer discovery operations."""

    if TYPE_CHECKING:
        adapters: dict[str, "BaseAdapter"]
        transport: "RedisTransport | None"

    async def discover_peers(
        self, redis_enabled: bool | None = None
    ) -> list[dict[str, object]]:  # guard: loose-dict - Adapter peer data
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Args:
            redis_enabled: Whether Redis is enabled. Defaults to True.

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
            - version: Runtime version advertised by the peer (optional)
            - channel: Deployment channel advertised by the peer (optional)
            - capability_set: Feature-IDs advertised by the peer
        """
        logger.debug("AdapterClient.discover_peers() called, adapters: %s", list(self.adapters.keys()))

        # Determine Redis enabled state - explicit param takes precedence
        is_redis_enabled = redis_enabled if redis_enabled is not None else True

        # Early return if Redis is disabled - no peer discovery without Redis
        if not is_redis_enabled:
            logger.debug("Redis disabled, skipping peer discovery")
            return []

        all_peers: list[dict[str, object]] = []  # guard: loose-dict - Adapter peer data

        # Peer discovery is a transport (Redis) capability; the transport lives
        # off the adapter registry, so include it alongside any adapters.
        peer_sources: list[tuple[str, BaseAdapter]] = list(self.adapters.items())
        if self.transport is not None:
            peer_sources.append(("redis", self.transport))

        # Collect peers from all sources
        for adapter_type, adapter in peer_sources:
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
                    if peer_info.version:
                        peer_dict["version"] = peer_info.version
                    if peer_info.channel:
                        peer_dict["channel"] = peer_info.channel
                    peer_dict["capability_set"] = peer_info.capability_set
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

    async def dispatch_remote_command(
        self,
        target_computer: str,
        command: str,
        metadata: MessageMetadata,
        *,
        session_id: str | None = None,
        timeout: float = 3.0,
        wait_for_response: bool = True,
    ) -> JsonValue:
        """Dispatch a command-typed request to a peer computer.

        The receiver maps the command string through its Redis command mapper.
        Fire-and-forget callers still use the command stream; they simply skip
        response reads after the message has been accepted by the transport.
        """
        logger.info(
            "Dispatching remote command",
            target_computer=target_computer,
            command=command,
            wait_for_response=wait_for_response,
        )
        message_id = await self.send_request(
            target_computer,
            command,
            metadata,
            session_id=session_id,
        )
        if not wait_for_response:
            return None

        response_text = await self.read_response(
            message_id,
            timeout=timeout,
            target_computer=target_computer,
        )
        return _parse_remote_dispatch_data(
            response_text,
            target_computer=target_computer,
            command=command,
        )

    def _get_transport_adapter(self) -> RemoteExecutionProtocol:
        """Return the Redis transport that backs remote execution.

        Raises:
            RuntimeError: If the transport is not available
        """
        if self.transport is None:
            raise RuntimeError("No transport adapter available for remote execution")
        return self.transport
