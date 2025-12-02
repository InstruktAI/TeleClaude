"""Unit tests for AdapterClient peer discovery aggregation."""

from datetime import datetime

import pytest

from teleclaude.core.models import PeerInfo


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
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=datetime.now(),
                adapter_type="telegram",
            ),
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=datetime.now(),
                adapter_type="telegram",
            ),
        ]
    )

    # Register adapter
    client.register_adapter("telegram", mock_client)

    # Test discovery (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
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
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=datetime.now(),
                adapter_type="telegram",
            )
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
            ),
            PeerInfo(
                name="server",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
            ),
        ]
    )

    # Register adapters
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test aggregation (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
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
    now = datetime.now()
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=now,
                adapter_type="telegram",
            )
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",  # Duplicate!
                status="online",
                last_seen=now,
                adapter_type="redis",
            ),
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=now,
                adapter_type="redis",
            ),
        ]
    )

    # Register adapters (order matters - first wins)
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test deduplication (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 2  # Not 3 - macbook deduplicated

    # First adapter (telegram) wins for "macbook"
    macbook_peer = next(p for p in peers if p["name"] == "macbook")
    assert macbook_peer["adapter_type"] == "telegram"


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
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
            )
        ]
    )

    # Register both adapters
    client.register_adapter("telegram", mock_failing_adapter)
    client.register_adapter("redis", mock_working_adapter)

    # Test that discovery continues despite failure (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
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

    # Test empty result (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_no_adapters():
    """Test behavior when no adapters are registered."""
    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Test discovery with no adapters (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_system_stats_passthrough():
    """Test that system_stats are passed through from PeerInfo to dict."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter with system_stats
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="server",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
                user="testuser",
                host="server.local",
                role="development",
                system_stats={
                    "memory": {"total_gb": 16.0, "available_gb": 8.0, "percent_used": 50.0},
                    "disk": {"total_gb": 500.0, "free_gb": 250.0, "percent_used": 50.0},
                    "cpu": {"percent_used": 25.0},
                },
            )
        ]
    )

    client.register_adapter("redis", mock_adapter)

    # Test that system_stats are passed through (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 1
    assert peers[0]["name"] == "server"
    assert peers[0]["role"] == "development"
    assert "system_stats" in peers[0]
    assert peers[0]["system_stats"]["memory"]["total_gb"] == 16.0
    assert peers[0]["system_stats"]["cpu"]["percent_used"] == 25.0


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_redis_disabled():
    """Test that discover_peers returns empty list when Redis is disabled."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter that would return peers
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="should-not-appear",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
            )
        ]
    )

    client.register_adapter("redis", mock_adapter)

    # Test with Redis disabled - should return empty list without calling adapter
    peers = await client.discover_peers(redis_enabled=False)
    assert len(peers) == 0
    assert peers == []
    # Adapter should NOT have been called
    mock_adapter.discover_peers.assert_not_called()
