"""Integration test for digest-triggered project refresh."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_peers_triggers_pull_on_digest_change(monkeypatch):
    """Refresh should pull projects when peer digest changes."""
    from teleclaude.adapters import redis_adapter as redis_adapter_module
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
    adapter.computer_name = "LocalPC"
    adapter.cache = MagicMock()

    adapter.pull_remote_projects_with_todos = AsyncMock()

    heartbeat = {
        "computer_name": "RemotePC",
        "last_seen": "2025-01-01T00:00:00Z",
        "projects_digest": "digest-1",
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(heartbeat).encode("utf-8"))
    adapter.redis = mock_redis

    monkeypatch.setattr(
        redis_adapter_module,
        "scan_keys",
        AsyncMock(return_value=[b"computer:RemotePC:heartbeat"]),
    )

    await adapter.refresh_peers_from_heartbeats()

    adapter.pull_remote_projects_with_todos.assert_awaited_once_with("RemotePC")

    adapter.pull_remote_projects_with_todos.reset_mock()
    await adapter.refresh_peers_from_heartbeats()

    adapter.pull_remote_projects_with_todos.assert_not_awaited()
