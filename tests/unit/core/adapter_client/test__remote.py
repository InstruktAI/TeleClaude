"""Characterization tests for teleclaude.core.adapter_client._remote."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.adapter_client._client import AdapterClient
from teleclaude.core.models import MessageMetadata, PeerInfo
from teleclaude.core.protocols import RemoteExecutionProtocol


def _make_transport_adapter() -> MagicMock:
    adapter = MagicMock(spec=RemoteExecutionProtocol)
    adapter.send_request = AsyncMock(return_value="msg-id-1")
    adapter.send_response = AsyncMock(return_value="resp-id-1")
    adapter.read_response = AsyncMock(return_value="response-data")
    adapter.discover_peers = AsyncMock(return_value=[])
    return adapter


def _make_peer_info(name: str, adapter_type: str = "redis") -> PeerInfo:
    return PeerInfo(
        name=name,
        status="online",
        last_seen=datetime.now(tz=UTC),
        adapter_type=adapter_type,
    )


class TestDiscoverPeers:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_disabled(self):
        client = AdapterClient()
        client.register_adapter("redis", _make_transport_adapter())

        result = await client.discover_peers(redis_enabled=False)

        assert result == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_uses_config_when_redis_enabled_not_provided(self):
        client = AdapterClient()

        with patch("teleclaude.core.adapter_client._remote.config") as mock_config:
            mock_config.redis.enabled = False
            result = await client.discover_peers()

        assert result == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_aggregates_and_deduplicates_peers_from_registered_adapters(self):
        client = AdapterClient()
        primary = _make_transport_adapter()
        secondary = _make_transport_adapter()
        primary.discover_peers = AsyncMock(return_value=[_make_peer_info("computer-a", adapter_type="redis")])
        secondary.discover_peers = AsyncMock(
            return_value=[_make_peer_info("computer-a", adapter_type="redis-secondary"), _make_peer_info("computer-b")]
        )
        client.register_adapter("redis", primary)
        client.register_adapter("redis-secondary", secondary)

        result = await client.discover_peers(redis_enabled=True)

        assert [peer["name"] for peer in result] == ["computer-a", "computer-b"]
        assert result[0]["adapter_type"] == "redis"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_keeps_optional_fields_when_present_and_skips_failing_adapter(self):
        client = AdapterClient()
        healthy = _make_transport_adapter()
        failing = _make_transport_adapter()
        peer = _make_peer_info("computer-b")
        peer.user = "alice"
        peer.host = "myhost"
        peer.ip = "192.168.1.1"
        peer.role = "worker"
        healthy.discover_peers = AsyncMock(return_value=[peer])
        failing.discover_peers = AsyncMock(side_effect=RuntimeError("network"))
        client.register_adapter("redis", healthy)
        client.register_adapter("redis-secondary", failing)

        result = await client.discover_peers(redis_enabled=True)

        assert result == [
            {
                "name": "computer-b",
                "status": "online",
                "last_seen": peer.last_seen,
                "adapter_type": "redis",
                "user": "alice",
                "host": "myhost",
                "ip": "192.168.1.1",
                "role": "worker",
            }
        ]


class TestRemoteExecutionRequests:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_request_raises_without_transport_adapter(self):
        client = AdapterClient()

        with pytest.raises(RuntimeError):
            await client.send_request("remote-pc", "cmd", MessageMetadata())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_request_delegates_to_transport(self):
        client = AdapterClient()
        transport = _make_transport_adapter()
        metadata = MessageMetadata()
        client.register_adapter("redis", transport)

        result = await client.send_request("remote-pc", "list_projects", metadata, session_id="sess-1")

        assert result == "msg-id-1"
        transport.send_request.assert_awaited_once_with("remote-pc", "list_projects", metadata, "sess-1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_response_raises_without_transport_adapter(self):
        client = AdapterClient()

        with pytest.raises(RuntimeError):
            await client.send_response("msg-1", "data")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_response_delegates_to_transport(self):
        client = AdapterClient()
        transport = _make_transport_adapter()
        client.register_adapter("redis", transport)

        result = await client.send_response("msg-1", "response-payload")

        assert result == "resp-id-1"
        transport.send_response.assert_awaited_once_with("msg-1", "response-payload")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_read_response_raises_without_transport_adapter(self):
        client = AdapterClient()

        with pytest.raises(RuntimeError):
            await client.read_response("msg-1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_read_response_delegates_to_transport(self):
        client = AdapterClient()
        transport = _make_transport_adapter()
        client.register_adapter("redis", transport)

        result = await client.read_response("msg-1", timeout=5.0, target_computer="remote")

        assert result == "response-data"
        transport.read_response.assert_awaited_once_with("msg-1", 5.0, "remote")
