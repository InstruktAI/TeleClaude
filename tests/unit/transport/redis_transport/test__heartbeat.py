"""Characterization tests for teleclaude.transport.redis_transport._heartbeat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestOnCacheChange:
    @pytest.mark.unit
    def test_is_a_noop_for_all_events(self, transport: RedisTransport) -> None:
        # Push-based sync is disabled; handler must not raise or have side effects
        transport._on_cache_change("session_update", {"key": "value"})
        transport._on_cache_change("unknown_event", None)


class TestSendHeartbeat:
    @pytest.mark.unit
    async def test_sets_key_with_ttl(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        mock_redis.setex.assert_called_once()
        key_arg, ttl_arg, _ = mock_redis.setex.call_args.args
        assert f"computer:{transport.computer_name}:heartbeat" == key_arg
        assert ttl_arg == transport.heartbeat_ttl

    @pytest.mark.unit
    async def test_payload_includes_computer_name(self, transport: RedisTransport) -> None:
        import json

        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert payload["computer_name"] == transport.computer_name

    @pytest.mark.unit
    async def test_payload_includes_last_seen(self, transport: RedisTransport) -> None:
        import json

        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert "last_seen" in payload

    @pytest.mark.unit
    async def test_includes_interested_in_when_cache_has_data_types(self, transport: RedisTransport) -> None:
        import json

        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        mock_cache = MagicMock()
        mock_cache.get_interested_computers.return_value = ["other-computer"]
        mock_cache.get_projects_digest.return_value = None
        transport._cache = mock_cache

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert "interested_in" in payload

    @pytest.mark.unit
    async def test_includes_projects_digest_when_available(self, transport: RedisTransport) -> None:
        import json

        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        mock_cache = MagicMock()
        mock_cache.get_interested_computers.return_value = []
        mock_cache.get_projects_digest.return_value = "abc123"
        transport._cache = mock_cache

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert payload["projects_digest"] == "abc123"
