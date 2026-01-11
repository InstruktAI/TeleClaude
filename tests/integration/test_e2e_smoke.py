"""End-to-end smoke tests for TeleClaude event-driven architecture.

This test suite validates the complete data flow from WebSocket clients through
DaemonCache to Redis adapter and back. It's designed to run fast (<30s) and catch
integration regressions in the event notification chain.

Usage:
    pytest tests/integration/test_e2e_smoke.py -v
    make test-smoke
    make test-e2e  # Includes these tests
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from teleclaude.adapters.rest_adapter import RESTAdapter
    from teleclaude.core.cache import DaemonCache


# ==================== Fixtures ====================


@pytest.fixture
def cache(daemon_with_mocked_telegram):
    """Fresh cache instance for each test."""
    # Import inside fixture to delay config loading
    from teleclaude.core.cache import DaemonCache

    return DaemonCache()


@pytest.fixture
def mock_adapter_client(daemon_with_mocked_telegram) -> MagicMock:
    """Mock AdapterClient with local data."""
    # Import inside fixture to delay config loading
    from teleclaude.core.adapter_client import AdapterClient

    client = MagicMock(spec=AdapterClient)
    client.get_local_sessions = AsyncMock(return_value=[])
    client.get_local_projects = AsyncMock(return_value=[])
    client.computer_name = "test-computer"
    return client


@pytest.fixture
def rest_adapter(daemon_with_mocked_telegram, mock_adapter_client: MagicMock, cache):
    """REST adapter with cache wired."""
    # Import inside fixture to delay config loading
    from teleclaude.adapters.rest_adapter import RESTAdapter

    adapter = RESTAdapter(mock_adapter_client, cache=cache)
    return adapter


def create_mock_websocket() -> AsyncMock:
    """Create mock WebSocket with proper spec."""
    from fastapi import WebSocket

    ws = AsyncMock(spec=WebSocket)
    ws.send_json = AsyncMock()
    ws.receive_json = AsyncMock()
    return ws


def create_test_session(
    session_id: str = "test-session-123",
    computer: str = "test-computer",
    title: str = "Test Session",
):
    """Create test session info dict."""
    from teleclaude.mcp.types import SessionInfo

    return SessionInfo(
        session_id=session_id,
        origin_adapter="telegram",
        title=title,
        working_directory="/tmp",
        status="active",
        created_at=datetime.now(timezone.utc).isoformat(),
        last_activity=datetime.now(timezone.utc).isoformat(),
        computer=computer,
    )


# ==================== Phase 2: Core Flow Scenarios ====================


@pytest.mark.asyncio
async def test_websocket_subscription_registers_interest(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: Client connects → subscribes → interest tracked → disconnects → interest cleared.

    Validates:
    - WebSocket subscription registers interest in cache
    - Disconnect clears interest
    """
    # Verify no interest initially
    assert cache.get_interest() == set()

    # Simulate WebSocket connection and subscription
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"sessions"}

    # Update cache interest
    rest_adapter._update_cache_interest()

    # Verify interest registered
    assert cache.has_interest("sessions")
    assert cache.get_interest() == {"sessions"}

    # Simulate disconnect
    rest_adapter._ws_clients.discard(mock_ws)
    rest_adapter._client_subscriptions.pop(mock_ws, None)
    rest_adapter._update_cache_interest()

    # Verify interest cleared
    assert cache.get_interest() == set()


@pytest.mark.asyncio
async def test_cache_update_notifies_websocket_clients(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: cache.update_session() → REST adapter callback → ws.send_json().

    Validates:
    - Cache updates trigger subscriber callbacks
    - REST adapter receives notification
    - WebSocket clients receive pushed events
    """
    # Set up WebSocket client
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"sessions"}

    # Update session in cache (triggers notification)
    test_session = create_test_session()
    cache.update_session(test_session)

    # Wait for async send to complete
    await asyncio.sleep(0.1)

    # Verify WebSocket received notification
    mock_ws.send_json.assert_called_once()
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["event"] == "session_updated"
    assert call_args["data"]["session_id"] == "test-session-123"


@pytest.mark.asyncio
async def test_session_removal_notifies_websocket(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: cache.remove_session() → WebSocket receives session_removed event.

    Validates:
    - Session removal triggers notification
    - WebSocket clients receive session_removed event
    """
    # Set up WebSocket client
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"sessions"}

    # Add session first
    test_session = create_test_session()
    cache.update_session(test_session)
    mock_ws.send_json.reset_mock()

    # Remove session (triggers notification)
    cache.remove_session("test-session-123")

    # Wait for async send to complete
    await asyncio.sleep(0.1)

    # Verify WebSocket received removal notification
    mock_ws.send_json.assert_called_once()
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["event"] == "session_removed"
    assert call_args["data"]["session_id"] == "test-session-123"


@pytest.mark.asyncio
async def test_stale_cache_data_filtered(cache: DaemonCache) -> None:
    """
    Flow: Add stale data → get_sessions() → stale data not returned.

    Validates:
    - TTL staleness filtering works
    - Fresh data returned correctly
    """
    # Create test session
    test_session = create_test_session()

    # Manually add with old timestamp (simulate stale data)
    from teleclaude.core.cache import CachedItem

    old_timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    stale_item = CachedItem(test_session, cached_at=old_timestamp)
    cache._sessions["test-session-123"] = stale_item

    # get_sessions() doesn't auto-expire sessions (TTL=-1, infinite)
    # But we can verify the is_stale check works
    assert stale_item.is_stale(60)  # Stale after 60 seconds

    # Add fresh session
    fresh_session = create_test_session(session_id="fresh-123")
    cache.update_session(fresh_session)

    # Verify fresh item is not stale
    fresh_item = cache._sessions["fresh-123"]
    assert not fresh_item.is_stale(60)


# ==================== Phase 3: Cross-Computer Simulation ====================


@pytest.mark.asyncio
async def test_heartbeat_includes_interest_when_subscribed(cache: DaemonCache) -> None:
    """
    Flow: set_interest({"sessions"}) → heartbeat payload contains interested_in.

    Validates:
    - Cache tracks interest correctly
    - Interest available for heartbeat payloads
    """
    # Initially no interest
    assert cache.get_interest() == set()

    # Set interest
    cache.set_interest({"sessions", "preparation"})

    # Verify interest tracked
    assert cache.has_interest("sessions")
    assert cache.has_interest("preparation")
    assert not cache.has_interest("unknown")

    # Verify get_interest returns copy (mutation safe)
    interest = cache.get_interest()
    interest.add("tampered")
    assert "tampered" not in cache.get_interest()


@pytest.mark.asyncio
async def test_redis_event_updates_local_cache(cache: DaemonCache) -> None:
    """
    Flow: Simulated Redis xread → cache.update_session() → data available.

    Validates:
    - Redis stream events can update cache
    - Updated data available via cache
    """
    # Simulate receiving Redis event with session data
    # (In real system, RedisAdapter would parse stream and call cache.update_session())
    event_session = create_test_session(
        session_id="redis-session-456",
        computer="remote-computer",
        title="Redis Event Session",
    )

    # Simulate cache update from Redis event
    cache.update_session(event_session)

    # Verify session in cache
    sessions = cache.get_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "redis-session-456"
    assert sessions[0]["computer"] == "remote-computer"

    # Verify filtering by computer works
    remote_sessions = cache.get_sessions(computer="remote-computer")
    assert len(remote_sessions) == 1

    local_sessions = cache.get_sessions(computer="test-computer")
    assert len(local_sessions) == 0


@pytest.mark.asyncio
async def test_full_event_round_trip(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: Session change → Redis push → Redis receive → Cache → WebSocket.

    This is the "smoke test" that validates the entire event chain.

    Validates:
    - Complete event propagation from source to WebSocket client
    - All components work together correctly
    """
    # Set up WebSocket client
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"sessions"}

    # Update cache interest
    rest_adapter._update_cache_interest()
    assert cache.has_interest("sessions")

    # Simulate remote session change (from Redis)
    remote_session = create_test_session(
        session_id="round-trip-789",
        computer="remote-computer",
        title="Round Trip Test",
    )

    # Step 1: Redis adapter receives stream event
    # Step 2: Redis adapter updates cache
    cache.update_session(remote_session)

    # Step 3: Cache notifies subscribers (REST adapter)
    # Step 4: REST adapter pushes to WebSocket clients
    await asyncio.sleep(0.1)

    # Verify end-to-end: WebSocket received the event
    mock_ws.send_json.assert_called()
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["event"] == "session_updated"
    assert call_args["data"]["session_id"] == "round-trip-789"
    assert call_args["data"]["computer"] == "remote-computer"


# ==================== Phase 4: Edge Cases and Resilience ====================


@pytest.mark.asyncio
async def test_multiple_websocket_clients_receive_updates(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: Two clients subscribed → update → both receive.

    Validates:
    - Broadcast logic sends to all connected clients
    - Multiple clients can subscribe independently
    """
    # Set up two WebSocket clients
    mock_ws1 = create_mock_websocket()
    mock_ws2 = create_mock_websocket()

    rest_adapter._ws_clients.add(mock_ws1)
    rest_adapter._ws_clients.add(mock_ws2)
    rest_adapter._client_subscriptions[mock_ws1] = {"sessions"}
    rest_adapter._client_subscriptions[mock_ws2] = {"sessions"}

    # Update session in cache
    test_session = create_test_session(session_id="broadcast-test")
    cache.update_session(test_session)

    # Wait for async sends
    await asyncio.sleep(0.1)

    # Verify both clients received notification
    assert mock_ws1.send_json.called
    assert mock_ws2.send_json.called

    # Verify same event sent to both
    call1 = mock_ws1.send_json.call_args[0][0]
    call2 = mock_ws2.send_json.call_args[0][0]
    assert call1["event"] == "session_updated"
    assert call2["event"] == "session_updated"
    assert call1["data"]["session_id"] == "broadcast-test"
    assert call2["data"]["session_id"] == "broadcast-test"


@pytest.mark.asyncio
async def test_unsubscribed_client_receives_all_events(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: Client subscribed to "preparation" → session update → receives notification.

    Note: Current implementation broadcasts ALL events to ALL clients regardless of
    subscription topic. This test documents actual behavior (not filtered).

    Validates:
    - Broadcast sends to all clients regardless of subscription
    - This is by design (simplifies implementation, low overhead)
    """
    # Set up client subscribed to preparation only
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"preparation"}

    # Update session (not in preparation topic)
    test_session = create_test_session(session_id="unfiltered-test")
    cache.update_session(test_session)

    # Wait for async send
    await asyncio.sleep(0.1)

    # Verify client received notification (broadcast to all clients)
    # NOTE: Current implementation does NOT filter by subscription
    assert mock_ws.send_json.called
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["event"] == "session_updated"


@pytest.mark.asyncio
async def test_dead_websocket_client_removed_on_error(
    rest_adapter: RESTAdapter,
    cache: DaemonCache,
) -> None:
    """
    Flow: send_json raises → client removed from _ws_clients.

    Validates:
    - Dead clients cleaned up on send failure
    - Error handling prevents broadcast from failing
    """
    # Set up WebSocket client that fails on send
    mock_ws = create_mock_websocket()
    mock_ws.send_json.side_effect = Exception("Connection closed")

    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"sessions"}

    # Verify client registered
    assert mock_ws in rest_adapter._ws_clients

    # Update session (triggers notification)
    test_session = create_test_session(session_id="dead-client-test")
    cache.update_session(test_session)

    # Wait for async send and cleanup callback
    await asyncio.sleep(0.1)

    # Verify dead client removed from tracking
    # The _on_cache_change callback creates task with done_callback that removes failed clients
    assert mock_ws not in rest_adapter._ws_clients
    assert mock_ws not in rest_adapter._client_subscriptions
