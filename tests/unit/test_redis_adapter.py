"""Unit tests for RedisAdapter."""

import json
import time
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.mark.asyncio
async def test_redis_adapter_initialization():
    """Test RedisAdapter initialization with config."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {
                "enabled": True,
                "url": "redis://localhost:6379",
                "password": "test_password",
                "max_connections": 10,
                "socket_timeout": 5,
            },
            "computer": {
                "name": "test_computer",
                "bot_username": "test_bot",
            },
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        assert adapter.computer_name == "test_computer"
        assert adapter.bot_username == "test_bot"
        assert adapter.redis_url == "redis://localhost:6379"
        assert adapter.redis_password == "test_password"


@pytest.mark.asyncio
async def test_redis_adapter_start():
    """Test RedisAdapter start creates Redis connection."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config, \
         patch("teleclaude.adapters.redis_adapter.Redis") as mock_redis_class:

        mock_get_config.return_value = {
            "redis": {
                "enabled": True,
                "url": "redis://localhost:6379",
                "password": "test_password",
            },
            "computer": {
                "name": "test_computer",
                "bot_username": "test_bot",
            },
        }

        # Mock Redis instance
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis_class.from_url.return_value = mock_redis

        adapter = RedisAdapter(mock_session_manager, mock_daemon)
        await adapter.start()

        # Verify Redis.from_url was called with correct params
        mock_redis_class.from_url.assert_called_once()
        call_args = mock_redis_class.from_url.call_args
        assert "redis://localhost:6379" in call_args[0]
        assert call_args[1]["password"] == "test_password"

        # Verify ping was called
        mock_redis.ping.assert_called_once()

        assert adapter._running is True

        # Cleanup
        await adapter.stop()


@pytest.mark.asyncio
async def test_redis_adapter_send_message():
    """Test sending message to Redis stream."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_session_manager.get_session = AsyncMock(return_value=Mock(
        session_id="test_session",
        adapter_metadata={
            "redis": {
                "output_stream": "output:test_session"
            }
        }
    ))
    mock_session_manager.update_session = AsyncMock()

    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1234567890-0")
        adapter.redis = mock_redis

        # Send message
        message_id = await adapter.send_message("test_session", "Hello Redis!")

        # Verify XADD was called
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "output:test_session"
        assert call_args[0][1][b"chunk"] == b"Hello Redis!"

        assert message_id == "1234567890-0"


@pytest.mark.asyncio
async def test_redis_adapter_discover_peers():
    """Test peer discovery via Redis heartbeat keys."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Mock Redis
        mock_redis = AsyncMock()

        # Mock heartbeat keys
        mock_redis.keys = AsyncMock(return_value=[
            b"computer:macbook:heartbeat",
            b"computer:workstation:heartbeat",
        ])

        # Mock heartbeat data
        async def mock_get(key):
            if key == b"computer:macbook:heartbeat":
                return json.dumps({
                    "computer_name": "macbook",
                    "bot_username": "macbook_bot",
                    "last_seen": datetime.now().isoformat(),
                }).encode("utf-8")
            elif key == b"computer:workstation:heartbeat":
                return json.dumps({
                    "computer_name": "workstation",
                    "bot_username": "workstation_bot",
                    "last_seen": datetime.now().isoformat(),
                }).encode("utf-8")
            return None

        mock_redis.get = mock_get
        adapter.redis = mock_redis

        # Discover peers
        peers = await adapter.discover_peers()

        # Verify results
        assert len(peers) == 2
        assert "macbook" in [p["name"] for p in peers]
        assert "workstation" in [p["name"] for p in peers]

        macbook_peer = next(p for p in peers if p["name"] == "macbook")
        assert macbook_peer["status"] == "online"
        assert macbook_peer["adapter_type"] == "redis"


@pytest.mark.asyncio
async def test_redis_adapter_create_channel():
    """Test creating Redis streams for session."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_session = Mock(
        session_id="test_session",
        adapter_metadata={}
    )
    mock_session_manager.get_session = AsyncMock(return_value=mock_session)
    mock_session_manager.update_session = AsyncMock()

    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Mock Redis
        adapter.redis = AsyncMock()

        # Create channel with AI-to-AI title format
        title = "$macbook > $workstation - Check logs"
        channel_id = await adapter.create_channel("test_session", title)

        # Verify stream names
        assert channel_id == "output:test_session"

        # Verify session metadata was updated
        mock_session_manager.update_session.assert_called_once()
        call_args = mock_session_manager.update_session.call_args
        assert call_args[0][0] == "test_session"

        metadata = call_args[1]["adapter_metadata"]
        assert metadata["redis"]["command_stream"] == "commands:workstation"
        assert metadata["redis"]["output_stream"] == "output:test_session"


@pytest.mark.asyncio
async def test_redis_adapter_parse_target_from_title():
    """Test parsing target computer from AI session title."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Test valid title
        target = adapter._parse_target_from_title("$macbook > $workstation - Check logs")
        assert target == "workstation"

        # Test another valid title
        target = adapter._parse_target_from_title("$comp1 > $comp2 - Debug issue")
        assert target == "comp2"

        # Test invalid title
        target = adapter._parse_target_from_title("Invalid title format")
        assert target is None


@pytest.mark.asyncio
async def test_redis_adapter_heartbeat():
    """Test heartbeat sends Redis key with TTL."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        adapter.redis = mock_redis

        # Send heartbeat
        await adapter._send_heartbeat()

        # Verify SETEX was called
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args

        # Verify key format
        assert call_args[0][0] == "computer:test_computer:heartbeat"

        # Verify TTL
        assert call_args[0][1] == adapter.heartbeat_ttl

        # Verify data
        data = json.loads(call_args[0][2])
        assert data["computer_name"] == "test_computer"
        assert data["bot_username"] == "test_bot"
        assert "last_seen" in data


@pytest.mark.asyncio
async def test_redis_adapter_delete_message():
    """Test deleting message from Redis stream."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_session_manager.get_session = AsyncMock(return_value=Mock(
        adapter_metadata={
            "redis": {"output_stream": "output:test_session"}
        }
    ))

    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.xdel = AsyncMock(return_value=1)
        adapter.redis = mock_redis

        # Delete message
        success = await adapter.delete_message("test_session", "1234567890-0")

        # Verify XDEL was called
        assert success is True
        mock_redis.xdel.assert_called_once_with("output:test_session", "1234567890-0")


@pytest.mark.asyncio
async def test_redis_adapter_get_max_message_length():
    """Test max message length for Redis."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Redis should support 4KB messages
        assert adapter.get_max_message_length() == 4096


@pytest.mark.asyncio
async def test_redis_adapter_get_ai_session_poll_interval():
    """Test AI session poll interval for Redis."""
    from teleclaude.adapters.redis_adapter import RedisAdapter

    mock_session_manager = Mock()
    mock_daemon = Mock()

    with patch("teleclaude.adapters.redis_adapter.get_config") as mock_get_config:
        mock_get_config.return_value = {
            "redis": {"enabled": True, "url": "redis://localhost:6379"},
            "computer": {"name": "test_computer", "bot_username": "test_bot"},
        }

        adapter = RedisAdapter(mock_session_manager, mock_daemon)

        # Redis should use fast polling (0.5s) for AI sessions
        assert adapter.get_ai_session_poll_interval() == 0.5
