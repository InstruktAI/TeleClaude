# Code Review: e2e-smoke-tests

**Reviewed**: 2026-01-11
**Reviewer**: Claude Opus 4.5 (Reviewer)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| 1. WebSocket subscription flow tested | ✅ | `test_websocket_subscription_registers_interest` |
| 2. Cache notification chain tested | ✅ | `test_cache_update_notifies_websocket_clients`, `test_session_removal_notifies_websocket` |
| 3. Cross-computer event simulation | ✅ | `test_redis_event_updates_local_cache`, `test_full_event_round_trip` |
| 4. TTL/staleness verified | ⚠️ | `test_stale_cache_data_filtered` tests `is_stale()` method but doesn't test actual filtering |
| 5. All tests pass in CI | ❌ | 2 tests fail with timeout due to socket conflicts in parallel execution |
| 6. Multiple client isolation | ✅ | `test_multiple_websocket_clients_receive_updates`, `test_unsubscribed_client_receives_all_events` |
| 7. Error resilience tested | ⚠️ | `test_dead_websocket_client_removed_on_error` (missing Redis failure test) |
| 8. Heartbeat interest advertising | ⚠️ | Tests cache interest tracking but not actual heartbeat payload integration |

## Critical Issues (must fix)

### 1. [code] Tests fail in parallel execution due to socket conflicts

**Location:** `tests/integration/test_e2e_smoke.py` fixtures at lines 31-59

**Description:** When running with `-n auto`, tests `test_stale_cache_data_filtered` and `test_unsubscribed_client_receives_all_events` fail with timeout errors. The root cause is:
- All tests depend on `daemon_with_mocked_telegram` fixture from conftest
- This fixture starts the REST adapter which binds to `/tmp/teleclaude-api.sock`
- Multiple pytest workers try to use the same socket path, causing "Address already in use" errors

**Evidence:**
```
OSError: [Errno 48] Address '/tmp/teleclaude-api.sock' is already in use
ERROR tests/integration/test_e2e_smoke.py::test_stale_cache_data_filtered - Failed: Timeout (>5.0s)
ERROR tests/integration/test_e2e_smoke.py::test_unsubscribed_client_receives_all_events - Failed: Timeout (>5.0s)
```

**Suggested fix:** Create a lighter fixture that only patches config loading without starting the daemon infrastructure. The tests only need:
1. Config module patched to avoid loading real config.yml
2. `DaemonCache` class available for instantiation

```python
@pytest.fixture
def patched_config(monkeypatch, tmp_path):
    """Patch config loading without starting daemon."""
    from unittest.mock import MagicMock
    from teleclaude import config as config_module

    mock_config = MagicMock()
    mock_config.computer.name = "test-computer"
    monkeypatch.setattr(config_module, "config", mock_config)
    yield mock_config

@pytest.fixture
def cache(patched_config):
    """Fresh cache instance for each test."""
    from teleclaude.core.cache import DaemonCache
    return DaemonCache()
```

### 2. [tests] Timing-based assertions using `asyncio.sleep()` are non-deterministic

**Location:** `tests/integration/test_e2e_smoke.py` lines 154, 189, 329, 368, 408, 444

**Description:** Tests use `await asyncio.sleep(0.1)` to wait for async callbacks. Per requirements: "No timing-dependent assertions (use explicit waits)". This pattern can cause:
- Flaky tests if 100ms isn't enough
- Silent test passes if callback never fires (assertion runs before callback completes)

**Suggested fix:** Use explicit synchronization instead of sleep:
```python
async def wait_for_call(mock_fn, timeout=1.0, interval=0.01):
    """Wait for mock to be called."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if mock_fn.called:
            return True
        await asyncio.sleep(interval)
    pytest.fail(f"Timeout waiting for {mock_fn} to be called")
```

## Important Issues (should fix)

### 3. [tests] Test `test_stale_cache_data_filtered` doesn't actually test filtering

**Location:** `tests/integration/test_e2e_smoke.py` lines 199-227

**Description:** The test verifies `is_stale(60)` returns True for old data, but never calls a method that actually filters stale data. The comment even acknowledges "get_sessions() doesn't auto-expire sessions (TTL=-1, infinite)".

**Suggested fix:** Either:
1. Test `get_computers()` which does expire stale entries
2. Rename test to `test_stale_check_detects_old_data` to accurately describe what it tests
3. Add mock for TTL behavior to verify filtering logic

### 4. [code] Tests access private attributes directly

**Location:** `tests/integration/test_e2e_smoke.py` lines 112-114, 145-147, 177-178, 215, 226, 308-311, 354-361, 399-401, 432-434

**Description:** Tests directly manipulate private attributes like `rest_adapter._ws_clients`, `rest_adapter._client_subscriptions`, `cache._sessions`. This couples tests to implementation details.

**Suggested fix:** For smoke tests that intentionally test internal behavior, document this choice with a comment explaining why implementation testing is appropriate. Or add public methods for test setup.

### 5. [tests] Missing error condition tests

**Location:** Entire file

**Description:** No tests verify error handling scenarios:
- What if `cache.update_session()` is called with invalid data?
- What if a cache subscriber callback throws an exception?
- What if Redis connection fails?

The cache has error handling (line 326-329 in cache.py) that swallows subscriber exceptions - this is untested.

**Suggested fix:** Add error condition tests:
```python
@pytest.mark.asyncio
async def test_broken_subscriber_does_not_break_other_subscribers(cache):
    """Verify a failing subscriber doesn't prevent other subscribers from receiving updates."""
    received = []

    def good_subscriber(event, data):
        received.append((event, data))

    def bad_subscriber(event, data):
        raise RuntimeError("Intentional failure")

    cache.subscribe(bad_subscriber)
    cache.subscribe(good_subscriber)

    test_session = create_test_session()
    cache.update_session(test_session)

    assert len(received) == 1, "Good subscriber should still receive notification"
```

### 6. [tests] `test_dead_websocket_client_removed_on_error` doesn't verify exception was raised

**Location:** `tests/integration/test_e2e_smoke.py` lines 417-449

**Description:** The test sets `mock_ws.send_json.side_effect = Exception(...)` but never verifies that `send_json` was actually called. If `_on_cache_change` is broken and never calls `send_json`, the test could still pass.

**Suggested fix:** Add assertion that send_json was called:
```python
assert mock_ws.send_json.called, "send_json should have been called to trigger the exception"
```

## Suggestions (nice to have)

### 7. [tests] Interest mutation safety test is incomplete

**Location:** `tests/integration/test_e2e_smoke.py` lines 253-256

**Description:** Tests `get_interest()` returns a copy but doesn't verify `set_interest()` also copies.

### 8. [comments] `test_unsubscribed_client_receives_all_events` documents potential design issue

**Location:** `tests/integration/test_e2e_smoke.py` lines 383-414

**Description:** Test explicitly validates that clients receive ALL events regardless of subscription - this documents wasteful broadcast behavior rather than testing filtering. Consider whether this is intentional.

## Strengths

- Well-organized test file with clear phase-based structure
- Comprehensive module docstring explaining purpose and usage
- Good test naming following scenario_behavior pattern
- Behavioral tests that validate outcomes (WebSocket received event, cache contains session)
- Proper async handling with `@pytest.mark.asyncio`
- Covers 10 distinct scenarios matching implementation plan
- Linting passes (pylint, mypy, pyright all clean)
- Mocks at architectural boundaries (WebSocket, AdapterClient)

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first

### Priority fixes:

1. **Critical:** Fix socket conflict causing test failures in parallel execution - refactor fixtures to not depend on full daemon infrastructure
2. **Critical:** Replace `asyncio.sleep()` timing with explicit synchronization to ensure deterministic tests
3. **Important:** Verify `test_stale_cache_data_filtered` actually tests filtering behavior or rename it
4. **Important:** Add assertion in dead client test to verify exception was triggered

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Critical #1: Socket conflict in parallel execution | Replaced `daemon_with_mocked_telegram` dependency with lightweight `patched_config` fixture that only patches config loading without starting daemon infrastructure | ed55cd3 |
| Critical #2: Non-deterministic timing assertions | Added `wait_for_call()` helper with explicit synchronization. Replaced all `asyncio.sleep(0.1)` calls with explicit waits except dead client test | 65d9a93 |
| Important #3: test_stale_cache_data_filtered doesn't test filtering | Changed test to use `get_computers()` which performs actual TTL filtering. Now verifies stale entries are filtered and removed | 3e430d8 |
| Important #6: Dead client test missing exception verification | Added assertion to verify `send_json` was called before checking cleanup behavior | 422d3f6 |

### Test Results

All 10 e2e smoke tests pass in both sequential and parallel execution:
- Sequential: 692 unit tests + 10 e2e tests passed in 0.61s
- Parallel (`-n auto`): All 10 tests passed in 1.65s with no socket conflicts

Ready for re-review.
