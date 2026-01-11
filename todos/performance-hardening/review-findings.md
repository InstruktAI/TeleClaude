# Code Review: performance-hardening

**Reviewed**: 2026-01-11
**Reviewer**: Claude Opus 4.5 (prime-reviewer)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| 1.1 Redis KEYS → SCAN Migration | ✅ | `scan_keys()` properly iterates cursor until 0; all 3 occurrences replaced |
| 1.2 Subprocess Timeout Enforcement | ✅ | `wait_with_timeout()` and `communicate_with_timeout()` implemented; all subprocess operations use them |
| 1.3 Task Lifecycle Management | ✅ | `TaskRegistry` implemented; integrated into daemon, redis_adapter, rest_adapter; shutdown calls `registry.shutdown()` |
| Phase 1 Acceptance Criteria | ✅ | Zero `redis.keys()` calls; all subprocess ops have timeouts; background tasks use registry |

## Critical Issues (must fix)

### 1. [error-handling] `terminal_bridge.py:64-68` - Infinite recursion risk in timeout handlers

**Description:** When a subprocess times out, `wait_with_timeout()` calls itself recursively to clean up the zombie. If the process is truly stuck and doesn't die within the nested timeout, this creates infinite recursion.

```python
process.kill()
await wait_with_timeout(process, SUBPROCESS_TIMEOUT_QUICK, "tmux operation")  # RECURSIVE!
```

**Suggested fix:** Replace recursion with direct `asyncio.wait_for()`:
```python
process.kill()
try:
    await asyncio.wait_for(process.wait(), timeout=2.0)
except asyncio.TimeoutError:
    logger.error("Process %d failed to terminate after SIGKILL", process.pid or -1)
```

### 2. [error-handling] `terminal_bridge.py:105-109` - Same recursion in `communicate_with_timeout()`

**Description:** Same infinite recursion risk as above.

**Suggested fix:** Same as issue #1.

### 3. [error-handling] `task_registry.py:56-58` - Task exceptions never surfaced

**Description:** The `spawn()` method creates tasks but never logs exceptions. If a spawned task raises an exception, it's silently lost.

```python
task.add_done_callback(self._tasks.discard)  # Only removes, never checks for exception!
```

**Suggested fix:** Add exception logging to the done callback:
```python
def _on_task_done(self, task: asyncio.Task[object]) -> None:
    self._tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("Background task %s failed: %s", task.get_name(), exc, exc_info=exc)

# In spawn():
task.add_done_callback(self._on_task_done)
```

## Important Issues (should fix)

### 4. [error-handling] `redis_adapter.py:612-616, 724-726, 1210-1212` - scan_keys errors return empty list

**Description:** When `scan_keys()` or Redis operations fail, errors are logged but empty lists are returned. Callers cannot distinguish "no peers online" from "Redis is down."

**Suggested fix:** Consider raising exceptions (fail-fast) or documenting this degradation mode clearly.

### 5. [error-handling] `redis_adapter.py:178-183` - Untracked task fallback when task_registry is None

**Description:** When `task_registry` is `None`, the code falls back to `asyncio.create_task()` without exception handling. These untracked tasks can fail silently.

**Suggested fix:** Either make `task_registry` required, or add done callbacks to untracked tasks.

### 6. [types] `terminal_bridge.py:27-29` - SubprocessTimeoutError lacks structured data

**Description:** The exception carries no structured data (pid, timeout value, operation). Callers must parse the message to understand what happened.

**Suggested fix:** Add attributes:
```python
class SubprocessTimeoutError(TimeoutError):
    def __init__(self, operation: str, timeout: float, pid: int | None = None) -> None:
        self.operation = operation
        self.timeout = timeout
        self.pid = pid
        super().__init__(f"{operation} timed out after {timeout}s")
```

### 7. [tests] `test_redis_adapter.py:72-73, 113-137` - Tests mock `keys` but code uses `scan`

**Description:** Two tests (`test_discover_peers_handles_invalid_json`, `test_discover_peers_skips_self`) mock `mock_redis.keys` but the actual code calls `scan_keys()`. Tests pass but are fragile.

**Suggested fix:** Update tests to use `mock_redis.scan` like `test_discover_peers_parses_heartbeat_data` does.

## Suggestions (nice to have)

### 8. [error-handling] `terminal_bridge.py:67-68` - ProcessLookupError silently passed

**Description:** `ProcessLookupError` is caught with `pass`, which is correct but reduces debugging visibility.

**Suggested fix:** Add debug-level logging:
```python
except ProcessLookupError:
    logger.debug("Process %d already terminated before kill", process.pid or -1)
```

### 9. [types] `task_registry.py:38` - spawn() could preserve return type

**Description:** The `spawn()` signature uses `Coroutine[object, object, object]` which loses the task's return type.

**Suggested fix:** Consider using `TypeVar` for better type inference:
```python
T = TypeVar("T")
def spawn(self, coro: Coroutine[object, object, T], name: str | None = None) -> asyncio.Task[T]:
```

### 10. [error-handling] `redis_adapter.py:1112-1116` - Complex lambda in done callback

**Description:** The done callback lambda is complex and could be clearer.

**Suggested fix:** Extract to a named function for clarity.

## Strengths

1. **Clean architecture**: New modules (`redis_utils.py`, `task_registry.py`) have single responsibilities
2. **Proper cursor iteration**: `scan_keys()` correctly iterates until cursor == 0
3. **Comprehensive timeout coverage**: All subprocess operations in `terminal_bridge.py` use timeout wrappers
4. **TaskRegistry design**: Done callback pattern elegantly handles auto-cleanup
5. **Graceful shutdown**: `registry.shutdown()` cancels all tasks with timeout
6. **Excellent test coverage**: All new components have comprehensive unit tests
7. **Follows project patterns**: Uses functions over classes where appropriate, explicit typing, proper logging

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first

The Phase 1 implementation meets all functional requirements. However, the critical issues around infinite recursion and silent task failures should be addressed before merging to prevent production incidents.

### Priority fixes:
1. Fix infinite recursion in `wait_with_timeout()` and `communicate_with_timeout()`
2. Add exception logging to `TaskRegistry` done callback
3. Update fragile test mocks in `test_redis_adapter.py`
