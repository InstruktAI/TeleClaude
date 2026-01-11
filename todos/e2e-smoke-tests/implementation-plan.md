# Implementation Plan: End-to-End Smoke Tests

## Overview

Single test file with 8-10 scenarios covering the complete event-driven architecture. Uses pytest fixtures to set up components and mocks to simulate cross-computer communication.

---

## Phase 1: Test Infrastructure Setup

**Goal:** Create test file with fixtures and helpers.

- [ ] **Task 1.1:** Create test file skeleton
  - File: `tests/integration/test_e2e_smoke.py`
  - Add module docstring explaining purpose
  - Import required modules

- [ ] **Task 1.2:** Create shared fixtures
  ```python
  @pytest.fixture
  def cache() -> DaemonCache:
      """Fresh cache instance for each test."""
      return DaemonCache()

  @pytest.fixture
  def mock_adapter_client() -> MagicMock:
      """Mock AdapterClient with local data."""
      client = MagicMock()
      client.get_local_sessions.return_value = []
      client.get_local_projects.return_value = []
      client.computer_name = "test-computer"
      return client

  @pytest.fixture
  def rest_adapter(mock_adapter_client, cache) -> RESTAdapter:
      """REST adapter with cache wired."""
      adapter = RESTAdapter(mock_adapter_client, socket_path="/tmp/test.sock")
      adapter.cache = cache
      return adapter
  ```

- [ ] **Task 1.3:** Create WebSocket mock helper
  ```python
  def create_mock_websocket() -> AsyncMock:
      """Create mock WebSocket with proper spec."""
      ws = AsyncMock(spec=WebSocket)
      ws.send_json = AsyncMock()
      ws.receive_json = AsyncMock()
      return ws
  ```

### Verification:
- Fixtures instantiate without error
- `pytest tests/integration/test_e2e_smoke.py --collect-only` shows test file

---

## Phase 2: Core Flow Scenarios

**Goal:** Implement the critical path tests.

- [ ] **Task 2.1:** Scenario - WebSocket subscription registers interest
  ```python
  async def test_websocket_subscription_registers_interest(rest_adapter, cache):
      """
      Flow: Client connects → subscribes → interest tracked → disconnects → interest cleared
      """
  ```

- [ ] **Task 2.2:** Scenario - Cache update reaches WebSocket
  ```python
  async def test_cache_update_notifies_websocket_clients(rest_adapter, cache):
      """
      Flow: cache.update_session() → REST adapter callback → ws.send_json()
      """
  ```

- [ ] **Task 2.3:** Scenario - Session removal notification
  ```python
  async def test_session_removal_notifies_websocket(rest_adapter, cache):
      """
      Flow: cache.remove_session() → WebSocket receives session_removed event
      """
  ```

- [ ] **Task 2.4:** Scenario - Stale data filtered by TTL
  ```python
  async def test_stale_cache_data_filtered(cache):
      """
      Flow: Add stale data → get_sessions() → stale data not returned
      """
  ```

### Verification:
- `pytest tests/integration/test_e2e_smoke.py -v` - 4 tests pass
- Tests complete in <5 seconds

---

## Phase 3: Cross-Computer Simulation

**Goal:** Test the Redis stream event flow with mocks.

- [ ] **Task 3.1:** Scenario - Heartbeat includes interest
  ```python
  async def test_heartbeat_includes_interest_when_subscribed(cache):
      """
      Flow: set_interest({"sessions"}) → heartbeat payload contains interested_in
      """
  ```

- [ ] **Task 3.2:** Scenario - Redis stream event updates cache
  ```python
  async def test_redis_event_updates_local_cache():
      """
      Flow: Simulated Redis xread → cache.update_session() → data available
      """
  ```
  - Mock Redis client
  - Simulate event payload from remote computer
  - Verify cache updated correctly

- [ ] **Task 3.3:** Scenario - Full round-trip simulation
  ```python
  async def test_full_event_round_trip():
      """
      Flow: Session change → Redis push → Redis receive → Cache → WebSocket
      """
  ```
  - This is the "smoke test" that validates the entire chain

### Verification:
- `pytest tests/integration/test_e2e_smoke.py -v` - 7 tests pass
- No Redis connection required (all mocked)

---

## Phase 4: Edge Cases and Resilience

**Goal:** Test error handling and edge cases.

- [ ] **Task 4.1:** Scenario - Multiple clients receive broadcasts
  ```python
  async def test_multiple_websocket_clients_receive_updates(rest_adapter, cache):
      """
      Flow: Two clients subscribed → update → both receive
      """
  ```

- [ ] **Task 4.2:** Scenario - Subscription filtering
  ```python
  async def test_unsubscribed_client_filtered(rest_adapter, cache):
      """
      Flow: Client subscribed to "preparation" → session update → no notification
      """
  ```
  - Note: Document actual behavior (may broadcast all events to all clients)

- [ ] **Task 4.3:** Scenario - Dead client cleanup
  ```python
  async def test_dead_websocket_client_removed_on_error(rest_adapter, cache):
      """
      Flow: send_json raises → client removed from _ws_clients
      """
  ```

### Verification:
- `pytest tests/integration/test_e2e_smoke.py -v` - 10 tests pass
- All tests complete in <15 seconds

---

## Phase 5: CI Integration

**Goal:** Ensure tests run in CI and document usage.

- [ ] **Task 5.1:** Add to Makefile
  ```makefile
  test-smoke:
      uv run pytest tests/integration/test_e2e_smoke.py -v --tb=short
  ```

- [ ] **Task 5.2:** Verify tests work with `make test-e2e`
  - Ensure new tests included in integration suite
  - No conflicts with existing tests

- [ ] **Task 5.3:** Add test docstrings
  - Each test has docstring explaining the flow
  - Module docstring explains purpose and usage

### Verification:
- `make test-smoke` runs successfully
- `make test-e2e` includes smoke tests
- Total runtime <30 seconds

---

## Test Scenarios Summary

| # | Scenario | Components Tested |
|---|----------|-------------------|
| 1 | WebSocket subscription | REST adapter, Cache interest |
| 2 | Cache update → WebSocket | Cache notify, REST push |
| 3 | Session removal | Cache, WebSocket |
| 4 | TTL staleness | Cache TTL logic |
| 5 | Heartbeat interest | Cache interest, heartbeat payload |
| 6 | Redis event → Cache | Redis adapter, Cache update |
| 7 | Full round-trip | All components |
| 8 | Multiple clients | Broadcast logic |
| 9 | Subscription filtering | Event routing |
| 10 | Dead client cleanup | Error handling |

---

## File Structure

```
tests/integration/
├── test_e2e_smoke.py          # New: E2E smoke tests
├── conftest.py                # Shared fixtures (if needed)
└── ...existing tests...
```

---

## Commit Format

```
feat(tests): add end-to-end smoke test suite

Comprehensive smoke tests for WebSocket/Cache/Redis event flow:
- WebSocket subscription and interest tracking
- Cache notification chain to WebSocket clients
- Cross-computer event simulation via mocked Redis
- TTL staleness filtering
- Multiple client broadcast
- Error resilience

Tests run in <30s, suitable for nightly CI.

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```
