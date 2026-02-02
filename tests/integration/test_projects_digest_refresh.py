"""Integration test for digest-triggered project refresh."""

from unittest.mock import ANY, MagicMock

import pytest

from tests.integration.conftest import MockRedisClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_peers_triggers_pull_on_digest_change():
    """Refresh should pull projects when peer digest changes."""
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import ProjectInfo
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    redis_client = MockRedisClient()

    remote_adapter = RedisTransport(mock_client)
    remote_adapter.redis = redis_client
    remote_adapter.computer_name = "RemotePC"
    remote_adapter.cache = DaemonCache()
    remote_adapter._running = True
    remote_adapter._redis_ready.set()

    local_adapter = RedisTransport(mock_client)
    local_adapter.redis = redis_client
    local_adapter.computer_name = "LocalPC"
    local_adapter.cache = DaemonCache()
    local_adapter._running = True
    local_adapter._redis_ready.set()
    local_adapter._schedule_refresh = MagicMock(return_value=True)

    remote_adapter.cache.apply_projects_snapshot(
        "RemotePC",
        [ProjectInfo(name="Alpha", path="/tmp/alpha")],
    )
    digest_first = remote_adapter.cache.get_projects_digest("RemotePC")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter._schedule_refresh.assert_called_once_with(
        computer="RemotePC",
        data_type="projects",
        reason="digest",
        force=True,
        on_success=ANY,
    )
    local_adapter._peer_digests["RemotePC"] = digest_first

    local_adapter._schedule_refresh.reset_mock()
    await local_adapter.refresh_peers_from_heartbeats()
    local_adapter._schedule_refresh.assert_not_called()

    remote_adapter.cache.apply_projects_snapshot(
        "RemotePC",
        [ProjectInfo(name="Alpha", path="/tmp/alpha"), ProjectInfo(name="Beta", path="/tmp/beta")],
    )
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter._schedule_refresh.assert_called_once_with(
        computer="RemotePC",
        data_type="projects",
        reason="digest",
        force=True,
        on_success=ANY,
    )
