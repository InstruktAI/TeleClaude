# Code Review: performance-hardening

**Reviewed**: 2026-01-12
**Reviewer**: Claude Opus 4.5 (prime-reviewer) - Re-review after fixes

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| 1.1 Redis KEYS → SCAN Migration | ✅ | `scan_keys()` properly iterates cursor until 0; all 3 occurrences replaced |
| 1.2 Subprocess Timeout Enforcement | ✅ | `wait_with_timeout()` and `communicate_with_timeout()` implemented; all subprocess operations use them |
| 1.3 Task Lifecycle Management | ✅ | `TaskRegistry` implemented; integrated into daemon, redis_adapter, rest_adapter; shutdown calls `registry.shutdown()` |
| Phase 1 Acceptance Criteria | ✅ | Zero `redis.keys()` calls; all subprocess ops have timeouts; background tasks use registry |

## Previous Issues Resolution

| Issue | Status | Verification |
|-------|--------|--------------|
| #1, #2: Infinite recursion in timeout handlers | ✅ FIXED | `terminal_bridge.py:84-91,127-134` now uses direct `asyncio.wait_for()` |
| #3: Task exceptions never surfaced | ✅ FIXED | `task_registry.py:38-52` logs exceptions with `exc_info=exc` |
| #4: scan_keys errors return empty list | ✅ DOCUMENTED | Docstrings explain graceful degradation behavior |
| #5: Untracked task fallback | ✅ FIXED | `redis_adapter.py:198-203` adds `_log_task_exception` callback |
| #6: SubprocessTimeoutError lacks structured data | ✅ FIXED | `terminal_bridge.py:32-53` has operation, timeout, pid attributes |
| #7: Tests mock keys but code uses scan | ⚠️ PARTIAL | 2 tests fixed, but 1 test remains (`test_connection_error_handling`) |

## Critical Issues (must fix)

### 1. [tests] `tests/unit/test_redis_adapter.py:234` - Test still mocks wrong method

**Description:** The `test_connection_error_handling` test mocks `mock_redis.keys` but the production code uses `scan_keys()` which calls `mock_redis.scan`. The test passes but doesn't actually test error handling for the SCAN-based implementation.

```python
mock_redis.keys = AsyncMock(side_effect=ConnectionError("Connection refused"))  # WRONG
```

**Suggested fix:** Change to mock `scan` instead:
```python
mock_redis.scan = AsyncMock(side_effect=ConnectionError("Connection refused"))
```

## Important Issues (should fix)

### 2. [error-handling] `redis_adapter.py:221-224` - Fallback tasks without exception callbacks

**Description:** When `task_registry` is None, three critical tasks are spawned without exception callbacks:
```python
self._message_poll_task = asyncio.create_task(self._poll_redis_messages())
self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
self._session_events_poll_task = asyncio.create_task(self._poll_session_events())
```
Unlike the connection task (line 203) which has `add_done_callback(self._log_task_exception)`, these tasks would silently swallow exceptions.

**Suggested fix:** Add `self._log_task_exception` callback to all three tasks.

### 3. [error-handling] `redis_adapter.py:1337-1339` - Output stream listener without callback

**Description:** When `task_registry` is None, output stream listener tasks have no exception callback:
```python
task = asyncio.create_task(self._poll_output_stream_for_messages(session_id))
```

**Suggested fix:** Add `self._log_task_exception` callback when task_registry is None.

### 4. [tests] TaskRegistry exception logging not tested

**Description:** The `_on_task_done` callback in `task_registry.py:38-52` logs exceptions with full tracebacks, but no test verifies this behavior.

**Suggested fix:** Add test that spawns a failing task and verifies `logger.error` is called with `exc_info`.

### 5. [tests] SubprocessTimeoutError structured data not tested

**Description:** Tests only verify the exception message string, not the structured attributes:
```python
assert "test operation timed out after 0.1s" in str(exc_info.value)  # Only tests message
```

**Suggested fix:** Add assertions for structured data:
```python
assert exc_info.value.operation == "test operation"
assert exc_info.value.timeout == 0.1
assert exc_info.value.pid == 12345
```

### 6. [types] `task_registry.py:38` - spawn() loses return type

**Description:** The `spawn()` signature uses `Coroutine[object, object, object]` which loses the task's return type. Callers get `Task[object]` instead of `Task[T]`.

**Suggested fix:** Use TypeVar for better type inference:
```python
T = TypeVar("T")
def spawn(self, coro: Coroutine[object, object, T], name: str | None = None) -> asyncio.Task[T]:
```

## Suggestions (nice to have)

### 7. [error-handling] `terminal_bridge.py:89-90, 132-133` - ProcessLookupError silent pass

**Description:** `ProcessLookupError` is caught with `pass`, reducing debugging visibility.

**Suggested fix:** Add debug-level logging:
```python
except ProcessLookupError:
    logger.debug("Process %d already terminated before kill", process.pid or -1)
```

### 8. [error-handling] `redis_adapter.py:1143-1146` - Lambda callback missing exc_info

**Description:** The lambda done callback logs exceptions without full tracebacks:
```python
lambda t: logger.error("Push task failed: %s", t.exception()) if ... else None
```

**Suggested fix:** Replace with proper callback that includes `exc_info=exc`.

### 9. [tests] Redis SCAN - empty intermediate batch not tested

**Description:** Redis SCAN can return empty batches mid-iteration (documented Redis behavior). `test_scan_keys_multiple_batches` tests clean 3-batch iteration but not this edge case.

## Out of Scope Findings

The silent-failure-hunter identified additional untracked tasks in files NOT part of this PR:
- `telegram_adapter.py:480` - heartbeat task
- `computer_registry.py:92-93` - registry tasks
- `codex_watcher.py:44` - poll task
- `polling_coordinator.py:71` - poll task
- `rest_adapter.py:511` - server task

These pre-date this work item and should be addressed in a separate PR.

## Strengths

1. **Clean architecture**: New modules (`redis_utils.py`, `task_registry.py`) have single responsibilities
2. **Proper cursor iteration**: `scan_keys()` correctly iterates until cursor == 0
3. **Comprehensive timeout coverage**: All subprocess operations use timeout wrappers
4. **TaskRegistry design**: Done callback pattern elegantly handles auto-cleanup
5. **Graceful shutdown**: `registry.shutdown()` cancels all tasks with timeout
6. **Good test coverage**: All new components have comprehensive unit tests
7. **Follows project patterns**: Functions over classes, explicit typing, proper logging
8. **Excellent type annotations**: Modern Python syntax (`int | None`, explicit return types)
9. **Good documentation**: Docstrings explain graceful degradation behavior

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

The Phase 1 implementation meets all functional requirements and previous critical issues (#1-#6) have been properly addressed. However, one critical test bug remains, and there are test coverage gaps for the new error handling behavior.

### Priority fixes:
1. **CRITICAL**: Fix `test_connection_error_handling` to mock `scan` instead of `keys` (test_redis_adapter.py:234)
2. **IMPORTANT**: Add exception callbacks to fallback tasks in redis_adapter.py:221-224
3. **IMPORTANT**: Add test for TaskRegistry exception logging
4. **IMPORTANT**: Add test for SubprocessTimeoutError structured attributes

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| #1 (critical): Test mocks keys instead of scan | Changed mock from redis.keys to redis.scan | 25d87fe |
| #2 (important): Fallback tasks without callbacks | Added _log_task_exception callbacks to message_poll, heartbeat, session_events tasks | aac60dc |
| #3 (important): Output stream listener without callback | Added _log_task_exception callback to output stream listener | aac60dc |
| #4 (important): TaskRegistry exception logging not tested | Added test_exception_logging_with_full_traceback | 27bde1f |
| #5 (important): SubprocessTimeoutError structured data not tested | Added structured attribute assertions (operation, timeout, pid) | 27bde1f |
| #6 (important): spawn() loses return type | Added TypeVar T for better type inference | 54a9650 |

All critical and important issues have been addressed. Tests: PASSING
