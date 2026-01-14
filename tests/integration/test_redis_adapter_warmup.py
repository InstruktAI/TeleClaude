"""Integration tests for Redis adapter warmup behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_startup_refreshes_remote_snapshot():
    """Adapter startup should trigger a remote snapshot refresh."""
    from teleclaude.adapters.redis_adapter import RedisAdapter
    from teleclaude.core.cache import DaemonCache

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
    adapter.cache = DaemonCache()

    adapter._connect_with_backoff = AsyncMock()
    adapter.refresh_remote_snapshot = AsyncMock()

    adapter._poll_redis_messages = AsyncMock()
    adapter._heartbeat_loop = AsyncMock()
    adapter._peer_refresh_loop = AsyncMock()
    adapter._poll_session_events = AsyncMock()

    await adapter.start()
    await adapter._connection_task

    adapter.refresh_remote_snapshot.assert_awaited_once()

    await adapter.stop()
