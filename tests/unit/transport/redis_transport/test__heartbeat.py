"""Characterization tests for teleclaude.transport.redis_transport._heartbeat."""

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
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert payload["computer_name"] == transport.computer_name

    @pytest.mark.unit
    async def test_payload_includes_last_seen(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert "last_seen" in payload

    @pytest.mark.unit
    async def test_payload_includes_identity_fields_from_get_computer_info(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = None

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        for key in ("computer_name", "last_seen", "user", "host", "role", "system_stats"):
            assert key in payload, f"heartbeat payload is missing identity field {key!r}"

    @pytest.mark.unit
    async def test_payload_omits_local_only_fields(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        transport._cache = MagicMock()

        await transport._send_heartbeat()

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        for key in ("tmux_binary", "is_local", "status", "interested_in", "projects_digest"):
            assert key not in payload, f"heartbeat payload unexpectedly included {key!r}"
