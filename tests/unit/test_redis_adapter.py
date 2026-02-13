"""Unit tests for Redis adapter."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.origins import InputOrigin


@pytest.mark.asyncio
async def test_discover_peers_parses_heartbeat_data():
    """Test that discover_peers correctly parses heartbeat data from Redis."""
    from teleclaude.transport.redis_transport import RedisTransport

    # Create adapter with mocked client
    mock_client = MagicMock()
    mock_client.read_response = AsyncMock(
        return_value=json.dumps(
            {
                "status": "success",
                "data": {
                    "user": "testuser",
                    "host": "remote.local",
                    "role": "development",
                    "system_stats": {"memory": {"percent_used": 50.0}},
                },
            }
        )
    )

    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(return_value=(0, [b"computer:RemotePC:heartbeat"]))
    mock_redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "computer_name": "RemotePC",
                "last_seen": datetime.now().isoformat(),
            }
        ).encode("utf-8")
    )
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    # Mock send_request to return a message ID
    adapter.send_request = AsyncMock(return_value="msg-123-request-id")

    # Call discover_peers
    peers = await adapter.discover_peers()

    # Verify results
    assert len(peers) == 1
    assert peers[0].name == "RemotePC"
    assert peers[0].status == "online"
    assert peers[0].user == "testuser"
    assert peers[0].host == "remote.local"


@pytest.mark.asyncio
async def test_populate_initial_cache_updates_computers_and_projects():
    """Initial cache population should update computers and pull projects."""
    from teleclaude.core.models import PeerInfo
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    mock_cache = MagicMock()
    adapter.cache = mock_cache

    peers = [
        PeerInfo(
            name="RemoteOne",
            status="online",
            last_seen=datetime.now(),
            adapter_type="redis",
            user="morriz",
            host="remote-one.local",
            role="dev",
            system_stats=None,
        ),
        PeerInfo(
            name="RemoteTwo",
            status="online",
            last_seen=datetime.now(),
            adapter_type="redis",
            user="morriz",
            host="remote-two.local",
            role="dev",
            system_stats=None,
        ),
    ]

    adapter.discover_peers = AsyncMock(return_value=peers)
    scheduled: list[str] = []

    def record_schedule(*, computer: str, **_kwargs) -> bool:
        scheduled.append(computer)
        return True

    adapter._schedule_refresh = record_schedule

    updated: list[str] = []

    def record_update(info):
        updated.append(info.name)

    mock_cache.update_computer = record_update

    await adapter._populate_initial_cache()

    assert updated == ["RemoteOne", "RemoteTwo"]
    assert set(scheduled) == {"RemoteOne", "RemoteTwo"}


@pytest.mark.asyncio
async def test_startup_populates_initial_cache():
    """Ensure startup flow populates initial cache after connecting."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter._running = True

    adapter._schedule_reconnect = MagicMock()
    adapter._await_redis_ready = AsyncMock()
    adapter._populate_initial_cache = AsyncMock()

    def spawn(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()

    adapter.task_registry = MagicMock()
    adapter.task_registry.spawn = spawn

    await adapter._ensure_connection_and_start_tasks()

    assert adapter._populate_initial_cache.call_args is not None


@pytest.mark.asyncio
async def test_discover_peers_handles_invalid_json():
    """Test that discover_peers handles corrupted heartbeat data gracefully."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to return invalid JSON
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(return_value=(0, [b"computer:RemotePC:heartbeat"]))
    mock_redis.get = AsyncMock(return_value=b"not valid json {{{")
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    # Should not crash, just return empty list
    peers = await adapter.discover_peers()
    assert peers == []


@pytest.mark.asyncio
async def test_stop_notification_emits_agent_stop_event():
    """stop_notification should emit agent stop event with minimal payload."""
    from teleclaude.core.events import AgentHookEvents
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    mock_client.agent_event_handler = AsyncMock()
    adapter = RedisTransport(mock_client)

    adapter.send_response = AsyncMock()

    data = {
        b"command": b"/stop_notification sess-123 RemotePC",
        b"timestamp": b"1",
        b"initiator": b"RemotePC",
        b"origin": b"telegram",
    }

    await adapter._handle_incoming_message("msg-1", data)

    mock_client.agent_event_handler.assert_called_once()
    context = mock_client.agent_event_handler.call_args[0][0]
    assert context.event_type == AgentHookEvents.AGENT_STOP


@pytest.mark.asyncio
async def test_discover_peers_skips_self():
    """Test that discover_peers excludes the local computer."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to return heartbeat for self
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(return_value=(0, [b"computer:LocalPC:heartbeat"]))
    mock_redis.get = AsyncMock(
        return_value=json.dumps(
            {
                "computer_name": "LocalPC",  # Same as adapter.computer_name
                "last_seen": datetime.now().isoformat(),
            }
        ).encode("utf-8")
    )
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    # Should skip self
    peers = await adapter.discover_peers()
    assert peers == []


@pytest.mark.asyncio
async def test_heartbeat_includes_required_fields():
    """Test heartbeat message includes all required fields."""
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import ProjectInfo
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "TestPC"
    adapter.heartbeat_ttl = 30
    adapter.cache = DaemonCache()

    # Mock Redis setex (used by _send_heartbeat)
    mock_redis = AsyncMock()
    captured_data = {}

    async def capture_setex(key, ttl, value):
        captured_data["key"] = key
        captured_data["ttl"] = ttl
        captured_data["value"] = value
        return True

    mock_redis.setex = capture_setex
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    projects = [ProjectInfo(name="Alpha", path="/tmp/alpha")]
    adapter.cache.apply_projects_snapshot("TestPC", projects)

    # Call _send_heartbeat
    await adapter._send_heartbeat()

    # Verify heartbeat was sent
    assert "key" in captured_data
    assert captured_data["key"] == "computer:TestPC:heartbeat"

    # Parse the heartbeat JSON
    heartbeat = json.loads(captured_data["value"])
    assert "computer_name" in heartbeat
    assert "last_seen" in heartbeat
    assert heartbeat["computer_name"] == "TestPC"
    assert heartbeat["projects_digest"] == adapter.cache.get_projects_digest("TestPC")


@pytest.mark.asyncio
async def test_send_message_adds_to_stream():
    """Test that send_message is a no-op for RedisTransport."""
    from teleclaude.core.models import (
        RedisTransportMetadata,
        Session,
        SessionAdapterMetadata,
        TransportAdapterMetadata,
    )
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Track xadd calls
    captured_calls = []

    async def capture_xadd(stream_name, fields, maxlen=None):
        captured_calls.append({"stream": stream_name, "fields": fields, "maxlen": maxlen})
        return b"1234567890-0"

    mock_redis = AsyncMock()
    mock_redis.xadd = capture_xadd
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    # Create test session with proper adapter_metadata
    session = Session(
        session_id="test-session-123",
        computer_name="RemotePC",
        tmux_session_name="test-tmux",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
    )
    # Set up adapter_metadata with redis channel info using proper encapsulation
    session.adapter_metadata = SessionAdapterMetadata(
        _transport=TransportAdapterMetadata(_redis=RedisTransportMetadata(channel_id="session:test-session-123:output"))
    )

    # Send message
    result = await adapter.send_message(session, "Hello world")

    # Verify no Redis stream writes occur
    assert result == ""
    assert captured_calls == []


@pytest.mark.asyncio
async def test_connection_error_handling():
    """Test Redis connection error handling returns empty peers list."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to raise connection error
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(side_effect=ConnectionError("Connection refused"))
    adapter._get_redis = AsyncMock(return_value=mock_redis)

    # Should handle error gracefully and return empty list
    peers = await adapter.discover_peers()
    assert peers == []


def test_projects_digest_is_stable_for_same_snapshot(tmp_path):
    """Digest should remain stable for equivalent project snapshots."""
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import ProjectInfo

    cache = DaemonCache()

    project_one = ProjectInfo(name="alpha", path=str(tmp_path / "alpha"))
    project_two = ProjectInfo(name="beta", path=str(tmp_path / "beta"))

    cache.apply_projects_snapshot("Local", [project_one, project_two])
    digest_first = cache.get_projects_digest("Local")

    # Same snapshot content, different order
    changed = cache.apply_projects_snapshot("Local", [project_two, project_one])
    digest_second = cache.get_projects_digest("Local")

    assert changed is False
    assert digest_first == digest_second
