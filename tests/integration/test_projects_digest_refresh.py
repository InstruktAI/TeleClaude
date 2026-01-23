"""Integration test for digest-triggered project refresh."""

from unittest.mock import ANY, MagicMock

import pytest

from tests.integration.conftest import MockRedisClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refresh_peers_triggers_pull_on_digest_change():
    """Refresh should pull projects when peer digest changes."""
    from teleclaude.core.cache import DaemonCache
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    redis_client = MockRedisClient()

    remote_adapter = RedisTransport(mock_client)
    remote_adapter.redis = redis_client
    remote_adapter.computer_name = "RemotePC"

    local_adapter = RedisTransport(mock_client)
    local_adapter.redis = redis_client
    local_adapter.computer_name = "LocalPC"
    local_adapter.cache = DaemonCache()
    local_adapter._schedule_refresh = MagicMock(return_value=True)

    remote_adapter._compute_projects_digest = MagicMock(return_value="digest-1")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter._schedule_refresh.assert_called_once_with(
        computer="RemotePC",
        data_type="projects",
        reason="digest",
        force=True,
        on_success=ANY,
    )
    local_adapter._peer_digests["RemotePC"] = "digest-1"

    local_adapter._schedule_refresh.reset_mock()
    await local_adapter.refresh_peers_from_heartbeats()
    local_adapter._schedule_refresh.assert_not_called()

    remote_adapter._compute_projects_digest = MagicMock(return_value="digest-2")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    local_adapter._schedule_refresh.assert_called_once_with(
        computer="RemotePC",
        data_type="projects",
        reason="digest",
        force=True,
        on_success=ANY,
    )
