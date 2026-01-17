"""Unit tests for Redis adapter."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call

import pytest


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
    adapter.redis = mock_redis

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
    adapter.pull_remote_projects_with_todos = AsyncMock()

    await adapter._populate_initial_cache()

    assert mock_cache.update_computer.call_count == 2
    adapter.pull_remote_projects_with_todos.assert_has_awaits([call("RemoteOne"), call("RemoteTwo")])


@pytest.mark.asyncio
async def test_startup_populates_initial_cache():
    """Ensure startup flow populates initial cache after connecting."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter._running = True

    adapter._connect_with_backoff = AsyncMock()
    adapter._populate_initial_cache = AsyncMock()

    def spawn(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()

    adapter.task_registry = MagicMock()
    adapter.task_registry.spawn = spawn

    await adapter._ensure_connection_and_start_tasks()

    adapter._populate_initial_cache.assert_awaited_once()


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
    adapter.redis = mock_redis

    # Should not crash, just return empty list
    peers = await adapter.discover_peers()
    assert peers == []


@pytest.mark.asyncio
async def test_stop_notification_emits_agent_stop_event():
    """stop_notification should emit agent stop event with minimal payload."""
    from teleclaude.core.events import AgentHookEvents, TeleClaudeEvents
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    mock_client.handle_event = AsyncMock(return_value={"status": "success"})

    adapter = RedisTransport(mock_client)
    adapter.send_response = AsyncMock()

    data = {
        b"command": b"/stop_notification sess-123 RemotePC",
        b"timestamp": b"1",
        b"initiator": b"RemotePC",
    }

    await adapter._handle_incoming_message("msg-1", data)

    assert mock_client.handle_event.await_count == 1
    _, kwargs = mock_client.handle_event.call_args
    assert kwargs["event"] == TeleClaudeEvents.AGENT_EVENT

    payload = kwargs["payload"]
    assert payload["event_type"] == AgentHookEvents.AGENT_STOP
    assert payload["data"]["session_id"] == "sess-123"
    assert payload["data"]["source_computer"] == "RemotePC"
    assert "transcript_path" not in payload["data"]
    assert "summary" not in payload["data"]


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
    adapter.redis = mock_redis

    # Should skip self
    peers = await adapter.discover_peers()
    assert peers == []


@pytest.mark.asyncio
async def test_heartbeat_includes_required_fields(monkeypatch):
    """Test heartbeat message includes all required fields."""
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)
    adapter.computer_name = "TestPC"
    adapter.heartbeat_ttl = 30

    # Mock Redis setex (used by _send_heartbeat)
    mock_redis = AsyncMock()
    captured_data = {}

    async def capture_setex(key, ttl, value):
        captured_data["key"] = key
        captured_data["ttl"] = ttl
        captured_data["value"] = value
        return True

    mock_redis.setex = capture_setex
    adapter.redis = mock_redis

    def _fake_digest() -> str:
        return "digest-123"

    monkeypatch.setattr(adapter, "_compute_projects_digest", _fake_digest)

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
    assert heartbeat["projects_digest"] == "digest-123"


@pytest.mark.asyncio
async def test_send_message_adds_to_stream():
    """Test that send_message adds message to Redis stream."""
    from teleclaude.core.models import (
        RedisTransportMetadata,
        Session,
        SessionAdapterMetadata,
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
    adapter.redis = mock_redis

    # Create test session with proper adapter_metadata
    session = Session(
        session_id="test-session-123",
        computer_name="RemotePC",
        tmux_session_name="test-tmux",
        origin_adapter="redis",
        title="Test Session",
    )
    # Set up adapter_metadata with redis channel info
    session.adapter_metadata = SessionAdapterMetadata(
        redis=RedisTransportMetadata(channel_id="session:test-session-123:output")
    )

    # Send message
    await adapter.send_message(session, "Hello world")

    # Verify xadd was called with correct stream
    assert len(captured_calls) == 1
    assert captured_calls[0]["stream"] == "session:test-session-123:output"


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
    adapter.redis = mock_redis

    # Should handle error gracefully and return empty list
    peers = await adapter.discover_peers()
    assert peers == []


def test_compute_projects_digest_is_deterministic(tmp_path, monkeypatch):
    """Digest should be deterministic regardless of trusted dir order."""
    from types import SimpleNamespace

    from teleclaude.config import config
    from teleclaude.transport.redis_transport import RedisTransport

    mock_client = MagicMock()
    adapter = RedisTransport(mock_client)

    project_one = tmp_path / "alpha"
    project_two = tmp_path / "beta"
    project_one.mkdir()
    project_two.mkdir()

    trusted_dirs = [
        SimpleNamespace(path=str(project_two)),
        SimpleNamespace(path=str(project_one)),
    ]

    monkeypatch.setattr(config.computer, "get_all_trusted_dirs", lambda: trusted_dirs)
    digest_first = adapter._compute_projects_digest()

    trusted_dirs.reverse()
    digest_second = adapter._compute_projects_digest()

    assert digest_first == digest_second
