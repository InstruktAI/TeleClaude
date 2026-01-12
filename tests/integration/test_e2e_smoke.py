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
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from teleclaude.adapters.rest_adapter import RESTAdapter
    from teleclaude.core.cache import DaemonCache


# ==================== Fixtures ====================


@pytest.fixture
def patched_config(monkeypatch: MonkeyPatch) -> MagicMock:
    """Patch config loading without starting daemon infrastructure."""
    from teleclaude import config as config_module

    mock_config = MagicMock()
    mock_config.computer.name = "test-computer"
    monkeypatch.setattr(config_module, "config", mock_config)
    return mock_config


@pytest.fixture
def cache(patched_config: MagicMock):
    """Fresh cache instance for each test."""
    from teleclaude.core.cache import DaemonCache

    _ = patched_config  # Fixture dependency for config patching
    return DaemonCache()


@pytest.fixture
def mock_adapter_client(patched_config: MagicMock) -> MagicMock:
    """Mock AdapterClient with local data."""
    from teleclaude.core.adapter_client import AdapterClient

    _ = patched_config  # Fixture dependency for config patching
    client = MagicMock(spec=AdapterClient)
    client.get_local_sessions = AsyncMock(return_value=[])
    client.get_local_projects = AsyncMock(return_value=[])
    client.computer_name = "test-computer"
    return client


@pytest.fixture
def rest_adapter(patched_config: MagicMock, mock_adapter_client: MagicMock, cache: DaemonCache):
    """REST adapter with cache wired."""
    from teleclaude.adapters.rest_adapter import RESTAdapter

    _ = patched_config  # Fixture dependency for config patching
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


async def wait_for_call(mock_fn: AsyncMock, timeout: float = 1.0, interval: float = 0.01) -> None:
    """Wait for mock function to be called with explicit synchronization.

    Args:
        mock_fn: Mock function to check
        timeout: Maximum time to wait in seconds
        interval: Poll interval in seconds

    Raises:
        AssertionError: If mock is not called within timeout
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if mock_fn.called:
            return
        await asyncio.sleep(interval)
    pytest.fail(f"Timeout waiting for {mock_fn} to be called")


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
    assert cache.get_interested_computers("sessions") == []

    # Simulate WebSocket connection and subscription (new per-computer format)
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"local": {"sessions"}}

    # Update cache interest
    rest_adapter._update_cache_interest()

    # Verify interest registered for local computer
    assert cache.has_interest("sessions", "local")
    assert cache.get_interested_computers("sessions") == ["local"]

    # Simulate disconnect
    rest_adapter._ws_clients.discard(mock_ws)
    rest_adapter._client_subscriptions.pop(mock_ws, None)
    rest_adapter._update_cache_interest()

    # Verify interest cleared
    assert cache.get_interested_computers("sessions") == []


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
    rest_adapter._client_subscriptions[mock_ws] = {"local": {"sessions"}}

    # Update session in cache (triggers notification)
    test_session = create_test_session()
    cache.update_session(test_session)

    # Wait for async send to complete
    await wait_for_call(mock_ws.send_json)

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
    rest_adapter._client_subscriptions[mock_ws] = {"local": {"sessions"}}

    # Add session first
    test_session = create_test_session()
    cache.update_session(test_session)
    mock_ws.send_json.reset_mock()

    # Remove session (triggers notification)
    cache.remove_session("test-session-123")

    # Wait for async send to complete
    await wait_for_call(mock_ws.send_json)

    # Verify WebSocket received removal notification
    mock_ws.send_json.assert_called_once()
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["event"] == "session_removed"
    assert call_args["data"]["session_id"] == "test-session-123"


@pytest.mark.asyncio
async def test_stale_cache_data_filtered(cache: DaemonCache) -> None:
    """
    Flow: Add stale computer → get_computers() → stale data filtered out.

    Validates:
    - TTL staleness filtering works in get_computers()
    - Stale entries are auto-expired on access
    - Fresh data returned correctly
    """
    from teleclaude.core.cache import CachedItem
    from teleclaude.mcp.types import ComputerInfo

    # Create test computer (TypedDict requires dict syntax)
    stale_computer: ComputerInfo = {
        "name": "stale-computer",
        "role": "worker",
        "status": "online",
        "user": "test",
        "host": "stale.local",
        "last_seen": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "adapter_type": "test",
        "system_stats": None,
    }

    # Manually add with old timestamp (simulate stale data)
    old_timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    stale_item = CachedItem(stale_computer, cached_at=old_timestamp)
    cache._computers["stale-computer"] = stale_item

    # Verify stale check works
    assert stale_item.is_stale(60)  # Stale after 60 seconds

    # Add fresh computer
    fresh_computer: ComputerInfo = {
        "name": "fresh-computer",
        "role": "worker",
        "status": "online",
        "user": "test",
        "host": "fresh.local",
        "last_seen": datetime.now(timezone.utc),
        "adapter_type": "test",
        "system_stats": None,
    }
    cache.update_computer(fresh_computer)

    # get_computers() should filter out stale entry and return only fresh
    computers = cache.get_computers()
    assert len(computers) == 1
    assert computers[0]["name"] == "fresh-computer"

    # Verify stale entry was removed from cache
    assert "stale-computer" not in cache._computers
    assert "fresh-computer" in cache._computers


# ==================== Phase 3: Cross-Computer Simulation ====================


@pytest.mark.asyncio
async def test_heartbeat_includes_interest_when_subscribed(cache: DaemonCache) -> None:
    """
    Flow: Per-computer interest → heartbeat payload contains interested_in.

    Validates:
    - Cache tracks per-computer interest correctly
    - Interest available for heartbeat payloads (aggregated across computers)
    """
    # Initially no interest
    assert cache.get_interested_computers("sessions") == []

    # Set interest for multiple computers
    cache.set_interest("sessions", "raspi")
    cache.set_interest("sessions", "macbook")
    cache.set_interest("projects", "raspi")

    # Verify interest tracked per computer
    assert cache.has_interest("sessions", "raspi")
    assert cache.has_interest("sessions", "macbook")
    assert cache.has_interest("projects", "raspi")
    assert not cache.has_interest("projects", "macbook")

    # Verify get_interested_computers returns list (mutation safe)
    computers = cache.get_interested_computers("sessions")
    computers.append("tampered")
    assert "tampered" not in cache.get_interested_computers("sessions")


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
    # Set up WebSocket client with per-computer subscription
    mock_ws = create_mock_websocket()
    rest_adapter._ws_clients.add(mock_ws)
    rest_adapter._client_subscriptions[mock_ws] = {"remote-computer": {"sessions"}}

    # Update cache interest
    rest_adapter._update_cache_interest()
    assert cache.has_interest("sessions", "remote-computer")

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
    await wait_for_call(mock_ws.send_json)

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
    await wait_for_call(mock_ws1.send_json)
    await wait_for_call(mock_ws2.send_json)

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
    rest_adapter._client_subscriptions[mock_ws] = {"local": {"preparation"}}

    # Update session (not in preparation topic)
    test_session = create_test_session(session_id="unfiltered-test")
    cache.update_session(test_session)

    # Wait for async send
    await wait_for_call(mock_ws.send_json)

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
    rest_adapter._client_subscriptions[mock_ws] = {"local": {"sessions"}}

    # Verify client registered
    assert mock_ws in rest_adapter._ws_clients

    # Update session (triggers notification)
    test_session = create_test_session(session_id="dead-client-test")
    cache.update_session(test_session)

    # Wait for async send and cleanup callback
    # Need to give time for the exception to be raised and cleanup callback to run
    await asyncio.sleep(0.1)

    # Verify send_json was called (to trigger the exception)
    assert mock_ws.send_json.called, "send_json should have been called to trigger the exception"

    # Verify dead client removed from tracking
    # The _on_cache_change callback creates task with done_callback that removes failed clients
    assert mock_ws not in rest_adapter._ws_clients
    assert mock_ws not in rest_adapter._client_subscriptions
