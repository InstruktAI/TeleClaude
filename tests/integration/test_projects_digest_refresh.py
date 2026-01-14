"""Integration test for digest-triggered project refresh."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.integration.conftest import MockRedisClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_peers_triggers_pull_on_digest_change():
    """Refresh should pull projects when peer digest changes."""
    from teleclaude.adapters.redis_adapter import RedisAdapter
    from teleclaude.core.cache import DaemonCache

    mock_client = MagicMock()
    redis_client = MockRedisClient()

    remote_adapter = RedisAdapter(mock_client)
    remote_adapter.redis = redis_client
    remote_adapter.computer_name = "RemotePC"

    local_adapter = RedisAdapter(mock_client)
    local_adapter.redis = redis_client
    local_adapter.computer_name = "LocalPC"
    local_adapter.cache = DaemonCache()
    local_adapter.pull_remote_projects_with_todos = AsyncMock()

    remote_adapter._compute_projects_digest = MagicMock(return_value="digest-1")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter.pull_remote_projects_with_todos.assert_awaited_once_with("RemotePC")

    local_adapter.pull_remote_projects_with_todos.reset_mock()
    await local_adapter.refresh_peers_from_heartbeats()
    local_adapter.pull_remote_projects_with_todos.assert_not_awaited()

    remote_adapter._compute_projects_digest = MagicMock(return_value="digest-2")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter.pull_remote_projects_with_todos.assert_awaited_once_with("RemotePC")
