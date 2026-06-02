"""Characterization tests for teleclaude.transport.redis_transport._peers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        t.computer_name = "local-computer"
        return t


class TestGetOnlineComputers:
    @pytest.mark.unit
    async def test_returns_empty_list_when_no_heartbeat_keys(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        with patch("teleclaude.transport.redis_transport._peers.scan_keys", AsyncMock(return_value=[])):
            result = await transport.get_online_computers()
        assert result == []

    @pytest.mark.unit
    async def test_excludes_self_from_results(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        payload = json.dumps({"computer_name": transport.computer_name}).encode()
        mock_redis.get = AsyncMock(return_value=payload)
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:local-computer:heartbeat"]),
        ):
            result = await transport.get_online_computers()
        assert result == []

    @pytest.mark.unit
    async def test_returns_sorted_computer_names(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)

        def make_payload(name: str) -> bytes:
            return json.dumps({"computer_name": name}).encode()

        mock_redis.get = AsyncMock(side_effect=[make_payload("zebra"), make_payload("alpha")])
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:zebra:heartbeat", b"computer:alpha:heartbeat"]),
        ):
            result = await transport.get_online_computers()
        assert result == ["alpha", "zebra"]

    @pytest.mark.unit
    async def test_returns_empty_list_on_redis_error(self, transport: RedisTransport) -> None:
        transport._get_redis = AsyncMock(return_value=AsyncMock())
        transport._schedule_reconnect = MagicMock()
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            result = await transport.get_online_computers()
        assert result == []
        transport._schedule_reconnect.assert_called_once()


class TestDiscoverPeers:
    @pytest.mark.unit
    async def test_returns_empty_list_when_no_heartbeat_keys(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        with patch("teleclaude.transport.redis_transport._peers.scan_keys", AsyncMock(return_value=[])):
            result = await transport.discover_peers()
        assert result == []

    @pytest.mark.unit
    async def test_skips_self_heartbeat(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        payload = json.dumps(
            {"computer_name": transport.computer_name, "last_seen": "2024-01-01T00:00:00+00:00"}
        ).encode()
        mock_redis.get = AsyncMock(return_value=payload)
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:local-computer:heartbeat"]),
        ):
            result = await transport.discover_peers()
        assert result == []

    @pytest.mark.unit
    async def test_returns_empty_list_on_redis_error(self, transport: RedisTransport) -> None:
        transport._get_redis = AsyncMock(return_value=AsyncMock())
        transport._schedule_reconnect = MagicMock()
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(side_effect=RuntimeError("scan failed")),
        ):
            result = await transport.discover_peers()
        assert result == []
        transport._schedule_reconnect.assert_called_once()

    @pytest.mark.unit
    async def test_peer_with_malformed_heartbeat_is_skipped(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        mock_redis.get = AsyncMock(return_value=None)  # heartbeat key expired between SCAN and GET
        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:other-peer:heartbeat"]),
        ):
            result = await transport.discover_peers()
        assert result == []

    @pytest.mark.unit
    async def test_returns_sorted_peers_by_name(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)

        peer_payloads = [
            json.dumps(
                {
                    "computer_name": "zebra-peer",
                    "last_seen": "2024-01-01T00:00:00+00:00",
                    "user": "u",
                    "host": "h",
                    "role": "worker",
                }
            ).encode(),
            json.dumps(
                {
                    "computer_name": "alpha-peer",
                    "last_seen": "2024-01-01T00:00:00+00:00",
                    "user": "u",
                    "host": "h",
                    "role": "worker",
                }
            ).encode(),
        ]
        mock_redis.get = AsyncMock(side_effect=peer_payloads)

        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:zebra-peer:heartbeat", b"computer:alpha-peer:heartbeat"]),
        ):
            result = await transport.discover_peers()
        names = [p.name for p in result]
        assert names == sorted(names)

    @pytest.mark.unit
    async def test_discover_peers_reads_bot_username_from_heartbeat(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        payload = json.dumps(
            {
                "computer_name": "other-peer",
                "last_seen": "2024-01-01T00:00:00+00:00",
                "user": "u",
                "host": "h",
                "role": "worker",
                "bot_username": "peer_bot",
            }
        ).encode()
        mock_redis.get = AsyncMock(return_value=payload)

        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:other-peer:heartbeat"]),
        ):
            result = await transport.discover_peers()

        assert result[0].bot_username == "peer_bot"

    @pytest.mark.unit
    async def test_discover_peers_defaults_bot_username_to_none_when_absent(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        payload = json.dumps(
            {
                "computer_name": "other-peer",
                "last_seen": "2024-01-01T00:00:00+00:00",
                "user": "u",
                "host": "h",
                "role": "worker",
            }
        ).encode()
        mock_redis.get = AsyncMock(return_value=payload)

        with patch(
            "teleclaude.transport.redis_transport._peers.scan_keys",
            AsyncMock(return_value=[b"computer:other-peer:heartbeat"]),
        ):
            result = await transport.discover_peers()

        assert result[0].bot_username is None
