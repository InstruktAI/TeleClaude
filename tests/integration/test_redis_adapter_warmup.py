"""Integration tests for Redis adapter warmup behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_startup_refreshes_remote_snapshot():
    """Adapter startup should trigger a remote snapshot refresh."""
    from teleclaude.core.cache import DaemonCache
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.cache = DaemonCache()

    # Mock the reconnect to immediately mark redis as ready
    def fake_schedule_reconnect(reason: str, error: Exception | None = None) -> None:
        mock_redis = MagicMock()
        mock_redis.aclose = AsyncMock()
        adapter.redis = mock_redis
        adapter._redis_ready.set()

    adapter._schedule_reconnect = fake_schedule_reconnect
    refreshed = []

    async def record_refresh():
        refreshed.append(True)

    adapter.refresh_remote_snapshot = record_refresh

    adapter._poll_redis_messages = AsyncMock()
    adapter._heartbeat_loop = AsyncMock()
    adapter._peer_refresh_loop = AsyncMock()
    adapter._poll_session_events = AsyncMock()

    await adapter.start()
    await adapter._connection_task

    assert refreshed == [True]

    await adapter.stop()
