"""Integration test for digest-triggered project refresh."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
    refresh_tasks: list[asyncio.Task[object]] = []
    pulled: list[str] = []

    def _spawn_refresh_task(coro, *, key):  # type: ignore[no-untyped-def]
        task = asyncio.create_task(coro)
        refresh_tasks.append(task)
        return task

    local_adapter._spawn_refresh_task = _spawn_refresh_task

    async def record_pull(computer: str) -> None:
        pulled.append(computer)
        return None

    local_adapter.pull_remote_projects_with_todos = record_pull

    remote_adapter.cache.apply_projects_snapshot(
        "RemotePC",
        [ProjectInfo(name="Alpha", path="/tmp/alpha")],
    )
    digest_first = remote_adapter.cache.get_projects_digest("RemotePC")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    assert len(refresh_tasks) == 1
    await refresh_tasks[-1]
    assert pulled == ["RemotePC"]
    assert local_adapter._peer_digests["RemotePC"] == digest_first

    tasks_before = len(refresh_tasks)
    await local_adapter.refresh_peers_from_heartbeats()
    assert local_adapter._peer_digests["RemotePC"] == digest_first
    assert len(refresh_tasks) == tasks_before
    assert pulled == ["RemotePC"]

    remote_adapter.cache.apply_projects_snapshot(
        "RemotePC",
        [ProjectInfo(name="Alpha", path="/tmp/alpha"), ProjectInfo(name="Beta", path="/tmp/beta")],
    )
    digest_second = remote_adapter.cache.get_projects_digest("RemotePC")
    await remote_adapter._send_heartbeat()
    await local_adapter.refresh_peers_from_heartbeats()

    assert len(refresh_tasks) == tasks_before + 1
    await refresh_tasks[-1]
    assert pulled == ["RemotePC", "RemotePC"]
    assert local_adapter._peer_digests["RemotePC"] == digest_second
