"""Characterization tests for teleclaude.transport.redis_transport._transport."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def adapter_client() -> MagicMock:
    client = MagicMock()
    client.agent_event_handler = AsyncMock()
    return client


@pytest.fixture
def transport(adapter_client: MagicMock) -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(adapter_client)
        t.redis = AsyncMock()
        return t


class TestInit:
    @pytest.mark.unit
    def test_not_running_on_init(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t._running is False

    @pytest.mark.unit
    def test_task_slots_are_none_on_init(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t._connection_task is None
        assert t._message_poll_task is None
        assert t._heartbeat_task is None
        assert t._peer_refresh_task is None
        assert t._reconnect_task is None

    @pytest.mark.unit
    def test_redis_ready_event_is_not_set_on_init(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert not t._redis_ready.is_set()

    @pytest.mark.unit
    def test_heartbeat_interval_is_30_seconds(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t.heartbeat_interval == 30

    @pytest.mark.unit
    def test_heartbeat_ttl_is_60_seconds(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t.heartbeat_ttl == 60

    @pytest.mark.unit
    def test_idle_poll_state_initialized(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t._idle_poll_last_log_at is None
        assert t._idle_poll_suppressed == 0

    @pytest.mark.unit
    def test_peer_digests_initialized_empty(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t._peer_digests == {}

    @pytest.mark.unit
    def test_refresh_state_initialized_empty(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t._refresh_last == {}
        assert t._refresh_tasks == {}

    @pytest.mark.unit
    def test_stores_client_reference(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t.client is adapter_client

    @pytest.mark.unit
    def test_cache_initially_none(self, adapter_client: MagicMock) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            t = RedisTransport(adapter_client)
        assert t.cache is None


class TestAllowedRefreshReasons:
    @pytest.mark.unit
    def test_startup_is_allowed(self) -> None:
        assert "startup" in RedisTransport._ALLOWED_REFRESH_REASONS

    @pytest.mark.unit
    def test_digest_is_allowed(self) -> None:
        assert "digest" in RedisTransport._ALLOWED_REFRESH_REASONS

    @pytest.mark.unit
    def test_interest_is_allowed(self) -> None:
        assert "interest" in RedisTransport._ALLOWED_REFRESH_REASONS

    @pytest.mark.unit
    def test_ttl_is_allowed(self) -> None:
        assert "ttl" in RedisTransport._ALLOWED_REFRESH_REASONS


class TestGetMaxMessageLength:
    @pytest.mark.unit
    def test_returns_4096(self, transport: RedisTransport) -> None:
        assert transport.get_max_message_length() == 4096


class TestGetAiSessionPollInterval:
    @pytest.mark.unit
    def test_returns_half_second(self, transport: RedisTransport) -> None:
        assert transport.get_ai_session_poll_interval() == 0.5


class TestStoreChannelId:
    @pytest.mark.unit
    def test_sets_channel_id_on_redis_meta(self, transport: RedisTransport) -> None:
        from teleclaude.core.models import SessionAdapterMetadata

        adapter_metadata = SessionAdapterMetadata()
        transport.store_channel_id(adapter_metadata, "channel-123")
        redis_meta = adapter_metadata.get_transport().get_redis()
        assert redis_meta.channel_id == "channel-123"

    @pytest.mark.unit
    def test_does_nothing_for_non_session_adapter_metadata(self, transport: RedisTransport) -> None:
        # Must not raise for unrecognized adapter_metadata type
        transport.store_channel_id(object(), "channel-123")
        transport.store_channel_id(None, "channel-123")


class TestCacheProperty:
    @pytest.mark.unit
    def test_setting_cache_subscribes_to_changes(self, transport: RedisTransport) -> None:
        mock_cache = MagicMock()
        transport.cache = mock_cache
        mock_cache.subscribe.assert_called_once_with(transport._on_cache_change)

    @pytest.mark.unit
    def test_setting_new_cache_unsubscribes_old_one(self, transport: RedisTransport) -> None:
        old_cache = MagicMock()
        new_cache = MagicMock()
        transport.cache = old_cache
        transport.cache = new_cache
        old_cache.unsubscribe.assert_called_once_with(transport._on_cache_change)

    @pytest.mark.unit
    def test_setting_none_cache_unsubscribes_old(self, transport: RedisTransport) -> None:
        old_cache = MagicMock()
        transport.cache = old_cache
        transport.cache = None
        old_cache.unsubscribe.assert_called_once_with(transport._on_cache_change)
        assert transport.cache is None
