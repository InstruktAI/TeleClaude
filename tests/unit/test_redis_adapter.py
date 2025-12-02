"""Unit tests for Redis adapter."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import PeerInfo


@pytest.mark.asyncio
async def test_discover_peers_parses_heartbeat_data():
    """Test that discover_peers correctly parses heartbeat data from Redis."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

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

    adapter = RedisAdapter(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.keys = AsyncMock(return_value=[b"computer:RemotePC:heartbeat"])
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
async def test_discover_peers_handles_invalid_json():
    """Test that discover_peers handles corrupted heartbeat data gracefully."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to return invalid JSON
    mock_redis = AsyncMock()
    mock_redis.keys = AsyncMock(return_value=[b"computer:RemotePC:heartbeat"])
    mock_redis.get = AsyncMock(return_value=b"not valid json {{{")
    adapter.redis = mock_redis

    # Should not crash, just return empty list
    peers = await adapter.discover_peers()
    assert peers == []


@pytest.mark.asyncio
async def test_discover_peers_skips_self():
    """Test that discover_peers excludes the local computer."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to return heartbeat for self
    mock_redis = AsyncMock()
    mock_redis.keys = AsyncMock(return_value=[b"computer:LocalPC:heartbeat"])
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
async def test_heartbeat_includes_required_fields():
    """Test heartbeat message includes all required fields."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
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


@pytest.mark.asyncio
async def test_send_message_adds_to_stream():
    """Test that send_message adds message to Redis stream."""
    from teleclaude.adapters.redis_adapter import RedisAdapter
    from teleclaude.core.models import (
        MessageMetadata,
        RedisAdapterMetadata,
        Session,
        SessionAdapterMetadata,
    )

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
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
        redis=RedisAdapterMetadata(channel_id="session:test-session-123:output")
    )

    # Send message
    metadata = MessageMetadata()
    result = await adapter.send_message(session, "Hello world", metadata)

    # Verify xadd was called with correct stream
    assert len(captured_calls) == 1
    assert captured_calls[0]["stream"] == "session:test-session-123:output"


@pytest.mark.asyncio
async def test_connection_error_handling():
    """Test Redis connection error handling returns empty peers list."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_client = MagicMock()
    adapter = RedisAdapter(mock_client)
    adapter.computer_name = "LocalPC"

    # Mock Redis to raise connection error
    mock_redis = AsyncMock()
    mock_redis.keys = AsyncMock(side_effect=ConnectionError("Connection refused"))
    adapter.redis = mock_redis

    # Should handle error gracefully and return empty list
    peers = await adapter.discover_peers()
    assert peers == []
