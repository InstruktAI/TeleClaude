"""Unit tests for AdapterClient peer discovery aggregation."""

from datetime import datetime

import pytest


@pytest.mark.asyncio
async def test_adapter_client_register_adapter():
    """Test adapter registration."""
    from unittest.mock import Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters
    mock_telegram_adapter = Mock()
    mock_redis_adapter = Mock()

    # Register adapters
    client.register_adapter("telegram", mock_telegram_adapter)
    client.register_adapter("redis", mock_redis_adapter)

    # Verify registration
    assert "telegram" in client.adapters
    assert "redis" in client.adapters
    assert client.adapters["telegram"] == mock_telegram_adapter
    assert client.adapters["redis"] == mock_redis_adapter


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_single_adapter():
    """Test peer discovery with single adapter."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter
    mock_client = Mock()
    mock_client.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "macbook",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "10s ago",
                "adapter_type": "telegram",
            },
            {
                "name": "workstation",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "5s ago",
                "adapter_type": "telegram",
            },
        ]
    )

    # Register adapter
    client.register_adapter("telegram", mock_client)

    # Test discovery
    peers = await client.discover_peers()
    assert len(peers) == 2
    assert "macbook" in [p["name"] for p in peers]
    assert "workstation" in [p["name"] for p in peers]


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_multiple_adapters():
    """Test peer discovery aggregation from multiple adapters."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters with different peers
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "macbook",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "10s ago",
                "adapter_type": "telegram",
            }
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "workstation",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "5s ago",
                "adapter_type": "redis",
            },
            {
                "name": "server",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "3s ago",
                "adapter_type": "redis",
            },
        ]
    )

    # Register adapters
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test aggregation
    peers = await client.discover_peers()
    assert len(peers) == 3
    assert "macbook" in [p["name"] for p in peers]
    assert "workstation" in [p["name"] for p in peers]
    assert "server" in [p["name"] for p in peers]


@pytest.mark.asyncio
async def test_adapter_client_deduplication():
    """Test that duplicate peers are deduplicated (first adapter wins)."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters with overlapping peers
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "macbook",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "10s ago",
                "adapter_type": "telegram",
            }
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "macbook",  # Duplicate!
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "5s ago",
                "adapter_type": "redis",
            },
            {
                "name": "workstation",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "3s ago",
                "adapter_type": "redis",
            },
        ]
    )

    # Register adapters (order matters - first wins)
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test deduplication
    peers = await client.discover_peers()
    assert len(peers) == 2  # Not 3 - macbook deduplicated

    # First adapter (telegram) wins for "macbook"
    macbook_peer = next(p for p in peers if p["name"] == "macbook")
    assert macbook_peer["adapter_type"] == "telegram"
    assert macbook_peer["last_seen_ago"] == "10s ago"


@pytest.mark.asyncio
async def test_adapter_client_handles_adapter_errors():
    """Test that errors from one adapter don't break discovery from others."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters - one fails, one succeeds
    mock_failing_adapter = Mock()
    mock_failing_adapter.discover_peers = AsyncMock(side_effect=Exception("Connection failed"))

    mock_working_adapter = Mock()
    mock_working_adapter.discover_peers = AsyncMock(
        return_value=[
            {
                "name": "workstation",
                "status": "online",
                "last_seen": datetime.now(),
                "last_seen_ago": "5s ago",
                "adapter_type": "redis",
            }
        ]
    )

    # Register both adapters
    client.register_adapter("telegram", mock_failing_adapter)
    client.register_adapter("redis", mock_working_adapter)

    # Test that discovery continues despite failure
    peers = await client.discover_peers()
    assert len(peers) == 1
    assert peers[0]["name"] == "workstation"


@pytest.mark.asyncio
async def test_adapter_client_empty_peers():
    """Test behavior when no peers are discovered."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter with no peers
    mock_client = Mock()
    mock_client.discover_peers = AsyncMock(return_value=[])

    client.register_adapter("telegram", mock_client)

    # Test empty result
    peers = await client.discover_peers()
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_no_adapters():
    """Test behavior when no adapters are registered."""
    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Test discovery with no adapters
    peers = await client.discover_peers()
    assert len(peers) == 0
    assert peers == []
