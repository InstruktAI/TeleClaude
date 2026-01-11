# Performance Hardening: Async Resilience & Data Efficiency

## Summary

Comprehensive performance hardening addressing systemic issues discovered through architectural review. The codebase has accumulated patterns that degrade under load, leak memory over time, and risk indefinite blocking. This work item establishes production-grade resilience across four domains: async safety, data layer efficiency, I/O resilience, and memory management.

**Scope**: Infrastructure hardening only. No functional changes to user-visible behavior.

---

## Goals

- **Eliminate indefinite blocking** - All async operations have bounded execution time
- **Prevent memory leaks** - All spawned tasks are tracked, all dicts are bounded
- **Improve cache efficiency** - O(1) lookups replace O(n) scans where possible
- **Reduce serialization overhead** - Hot paths avoid unnecessary conversions
- **Establish production patterns** - Code serves as reference for future development

## Non-Goals

- No new features or user-facing changes
- No API contract changes (internal refactoring only)
- No database schema changes (optimization within existing schema)
- No changes to external service integrations (Telegram, Redis protocols unchanged)
- No premature optimization of cold paths

---

## Current State Analysis

### Critical Issues (Production Risk)

| Issue | Location | Risk |
|-------|----------|------|
| Blocking Redis KEYS | `redis_adapter.py` (3x) | Blocks entire Redis server; O(n) scan |
| Subprocess wait() without timeout | `terminal_bridge.py` (8+ functions) | Indefinite hang if process stalls |
| Fire-and-forget async tasks | `rest_adapter.py`, `redis_adapter.py` | Memory leak; orphaned coroutines |

### High Priority Issues (Degradation Under Load)

| Issue | Location | Impact |
|-------|----------|--------|
| O(n) cache filtering | `cache.py:get_*()` | Linear scan on every access |
| Blocking psutil in async | `terminal_bridge.py:get_system_stats()` | 100ms event loop block |
| TUI blocking async in sync | `tui/app.py:run_until_complete()` | Defeats async benefits |
| Hard-coded 1s delays | `output_poller.py`, `terminal_bridge.py` | Unnecessary latency |
| Heavy serialization | `models.py:Session.to_dict()/from_dict()` | 25+ field conversion per cache hit |

### Technical Debt (Correctness)

| Issue | Location | Impact |
|-------|----------|--------|
| Listener race conditions | `adapter_client.py:_listeners` | Concurrent dict modification |
| Unbounded debounce state | Event handlers | Memory grows indefinitely |
| No timeout on event dispatch | `adapter_client.py` | Slow handler blocks pipeline |
| Duplicate DB functions | `db.py` | Code smell; maintenance burden |
| Incorrect Redis stream position | `redis_adapter.py` | Re-reads history on reconnect |

---

## Functional Requirements

### Phase 1: Critical Safety (Must Complete First)

#### 1.1 Redis KEYS → SCAN Migration

**Current behavior**: `redis.keys("pattern*")` blocks Redis server while scanning all keys.

**Required change**: Replace with `SCAN` cursor iteration.

```python
# BEFORE (blocking)
keys = await redis.keys("sessions:*")

# AFTER (non-blocking cursor)
async def scan_keys(redis, pattern: str) -> list[bytes]:
    keys = []
    cursor = b"0"
    while cursor:
        cursor, batch = await redis.scan(cursor, match=pattern, count=100)
        keys.extend(batch)
        if cursor == b"0":
            break
    return keys
```

**Locations**: Search `redis_adapter.py` for `.keys(` - expect 3 occurrences.

**Acceptance**: No `redis.keys()` calls remain; equivalent functionality via SCAN.

#### 1.2 Subprocess Timeout Enforcement

**Current behavior**: `process.wait()` blocks indefinitely if subprocess hangs.

**Required change**: All subprocess waits must have explicit timeout.

```python
# BEFORE (can block forever)
await process.wait()

# AFTER (bounded execution)
try:
    await asyncio.wait_for(process.wait(), timeout=30.0)
except asyncio.TimeoutError:
    process.kill()
    await process.wait()  # Clean up zombie
    raise SubprocessTimeoutError(f"Process {process.pid} timed out after 30s")
```

**Locations**: `terminal_bridge.py` - audit all `wait()`, `communicate()`, and `read()` calls.

**Acceptance**: Every subprocess operation has explicit timeout; timeout values are configurable via constants at module level.

#### 1.3 Task Lifecycle Management

**Current behavior**: `asyncio.create_task()` spawns tasks that are never awaited or cancelled.

**Required change**: Implement task registry pattern.

```python
class TaskRegistry:
    """Track all spawned tasks for graceful shutdown."""

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()

    def spawn(self, coro: Coroutine, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self, timeout: float = 5.0):
        """Cancel all tasks and wait for completion."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=timeout)
```

**Locations**:
- `rest_adapter.py:_on_cache_change()` - fire-and-forget WebSocket broadcast
- `redis_adapter.py` - fire-and-forget event dispatch
- Any other `asyncio.create_task()` without corresponding await/cancel

**Acceptance**:
- All background tasks are registered
- Daemon shutdown awaits/cancels all tasks
- No orphaned tasks after shutdown

---

### Phase 2: Data Layer Efficiency

#### 2.1 Cache Index Structures

**Current behavior**: `get_computers()`, `get_sessions()`, `get_projects()` iterate entire dict and filter.

**Required change**: Add secondary index dicts for common access patterns.

```python
class CentralCache:
    def __init__(self):
        # Primary storage (unchanged)
        self._computers: dict[str, CachedValue[ComputerInfo]] = {}
        self._sessions: dict[str, CachedValue[Session]] = {}

        # Secondary indexes (new)
        self._sessions_by_computer: dict[str, set[str]] = defaultdict(set)
        self._sessions_by_status: dict[str, set[str]] = defaultdict(set)

    def set_session(self, session: Session) -> None:
        session_id = session.session_id
        # Update primary
        self._sessions[session_id] = CachedValue(session)
        # Update indexes
        self._sessions_by_computer[session.computer].add(session_id)
        self._sessions_by_status[session.status].add(session_id)

    def get_sessions_for_computer(self, computer: str) -> list[Session]:
        # O(k) where k = sessions for this computer, not O(n) total sessions
        return [
            self._sessions[sid].data
            for sid in self._sessions_by_computer.get(computer, set())
            if sid in self._sessions and not self._sessions[sid].is_stale(60)
        ]
```

**Acceptance**:
- Common queries (by computer, by status) are O(k) not O(n)
- Index maintenance is encapsulated in setter methods
- No external API changes

#### 2.2 Lazy Serialization

**Current behavior**: `Session.to_dict()` converts all 25+ fields including nested datetime/JSON on every call.

**Required change**: Cache serialized form; invalidate on mutation.

```python
@dataclass
class Session:
    # ... existing fields ...
    _cached_dict: dict | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        if self._cached_dict is None:
            self._cached_dict = self._serialize()
        return self._cached_dict

    def _serialize(self) -> dict:
        # Actual serialization logic (current to_dict body)
        ...

    def _invalidate_cache(self) -> None:
        self._cached_dict = None
```

**Note**: Session is currently a frozen dataclass. If mutation is truly impossible, caching is automatic. Verify no mutation patterns exist before implementing.

**Acceptance**:
- Repeated `to_dict()` calls return cached result
- Memory overhead acceptable (one dict per session)

#### 2.3 Deduplicate Database Functions

**Current behavior**: `get_all_sessions()` and `get_active_sessions()` have identical implementations.

**Required change**: Single implementation with filter parameter.

```python
async def get_sessions(
    self,
    *,
    status_filter: list[str] | None = None,
    computer_filter: str | None = None,
    limit: int | None = None
) -> list[Session]:
    """Unified session query with optional filters."""
    ...

# Convenience aliases (optional, for backwards compatibility during transition)
async def get_all_sessions(self) -> list[Session]:
    return await self.get_sessions()

async def get_active_sessions(self) -> list[Session]:
    return await self.get_sessions(status_filter=["active", "running"])
```

**Acceptance**:
- Single source of truth for session queries
- Existing callers continue to work (if aliases kept) or are migrated

---

### Phase 3: I/O Resilience

#### 3.1 Configurable Polling Intervals

**Current behavior**: Hard-coded `await asyncio.sleep(1.0)` in polling loops.

**Required change**: Module-level constants, ideally from config.

```python
# Module constants (can later be config-driven)
POLL_INTERVAL_DEFAULT = 1.0
POLL_INTERVAL_MIN = 0.1
POLL_INTERVAL_MAX = 30.0

class OutputPoller:
    def __init__(self, poll_interval: float = POLL_INTERVAL_DEFAULT):
        self._poll_interval = max(POLL_INTERVAL_MIN, min(poll_interval, POLL_INTERVAL_MAX))
```

**Locations**: `output_poller.py`, `terminal_bridge.py`

**Acceptance**: All sleep durations use named constants; values are within sane bounds.

#### 3.2 Fix Exponential Backoff Reset

**Current behavior**: Backoff increases on failure but never resets on success.

**Required change**: Reset backoff after successful operation.

```python
class BackoffController:
    def __init__(self, initial: float = 1.0, max_backoff: float = 30.0, multiplier: float = 2.0):
        self._initial = initial
        self._max = max_backoff
        self._multiplier = multiplier
        self._current = initial

    def failure(self) -> float:
        """Record failure, return sleep duration."""
        delay = self._current
        self._current = min(self._current * self._multiplier, self._max)
        return delay

    def success(self) -> None:
        """Reset backoff after successful operation."""
        self._current = self._initial
```

**Acceptance**: After recovery from errors, backoff resets to initial value.

#### 3.3 Async-Safe System Stats

**Current behavior**: `psutil.cpu_percent(interval=0.1)` blocks event loop for 100ms.

**Required change**: Run in thread pool executor.

```python
async def get_system_stats() -> SystemStats:
    loop = asyncio.get_running_loop()
    cpu = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=0.1))
    # Memory is non-blocking, can stay sync
    mem = psutil.virtual_memory()
    return SystemStats(cpu_percent=cpu, memory_percent=mem.percent)
```

**Acceptance**: No blocking calls in async context; event loop latency < 10ms.

---

### Phase 4: Memory Management

#### 4.1 Bounded State Dictionaries

**Current behavior**: `_last_stop_time`, `_prev_state`, `_active_field` dicts grow without bounds.

**Required change**: Implement bounded dict with LRU eviction or explicit cleanup.

```python
from collections import OrderedDict

class BoundedDict(OrderedDict):
    """Dict with maximum size, evicts oldest entries."""

    def __init__(self, max_size: int = 1000):
        super().__init__()
        self._max_size = max_size

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self._max_size:
            self.popitem(last=False)
```

**Locations**:
- `adapter_client.py:_last_stop_time`
- `tui/views/sessions.py:_prev_state`
- `tui/views/preparation.py:_active_field`

**Acceptance**: No dict can grow beyond configured maximum (default 1000 entries).

#### 4.2 Listener Cleanup on Session Close

**Current behavior**: Listeners may persist after session ends.

**Required change**: Explicit cleanup when session transitions to terminal state.

```python
async def on_session_closed(self, session_id: str) -> None:
    """Clean up all resources associated with session."""
    # Remove from listener registry
    self._listeners.pop(session_id, None)
    # Remove from debounce state
    self._last_stop_time.pop(session_id, None)
    # Log cleanup
    logger.debug("Cleaned up resources for session %s", session_id)
```

**Acceptance**:
- Session closure triggers resource cleanup
- Memory usage remains stable over time (verify with long-running test)

#### 4.3 Fix Redis Stream Positioning

**Current behavior**: `xread(..., streams={stream: b"0"})` re-reads entire stream history on reconnect.

**Required change**: Use `b"$"` for "only new messages" or track last-seen ID.

```python
# For "only new messages from now"
await redis.xread(streams={stream: b"$"}, block=5000)

# For "resume from last seen" (if durability needed)
class StreamReader:
    def __init__(self):
        self._last_id: dict[str, bytes] = {}

    async def read(self, redis, stream: str) -> list:
        last = self._last_id.get(stream, b"$")
        results = await redis.xread(streams={stream: last}, block=5000)
        if results:
            # Update last seen ID
            self._last_id[stream] = results[-1][0]  # message ID
        return results
```

**Acceptance**: Reconnection does not replay historical messages unless explicitly requested.

---

## Testing Requirements

### Unit Tests

Each fix must have corresponding unit tests:

1. **Redis SCAN** - Mock redis, verify SCAN cursor iteration, not KEYS
2. **Subprocess timeout** - Mock process that hangs, verify timeout triggers kill
3. **Task registry** - Spawn tasks, call shutdown, verify all cancelled
4. **Cache indexes** - Verify O(1) lookup behavior (could use timing assertions)
5. **Bounded dict** - Insert beyond max_size, verify oldest evicted
6. **Backoff reset** - Simulate failures then success, verify reset

### Integration Tests

1. **Memory stability** - Long-running test that creates/destroys sessions, verify RSS stable
2. **Graceful shutdown** - Start daemon with active tasks, SIGTERM, verify clean exit

### Performance Benchmarks (Optional)

1. **Cache access** - Benchmark get_sessions() with 100/1000/10000 sessions
2. **Serialization** - Benchmark to_dict() with caching vs without

---

## Observability

### Logging

Add structured logs for:

- Task spawn/complete/cancel events (DEBUG level)
- Subprocess timeout events (WARNING level)
- Cache index rebuild events (DEBUG level)
- Memory cleanup events (DEBUG level)

### Metrics (If Applicable)

Consider tracking:

- Active task count
- Cache hit/miss ratio
- Subprocess timeout frequency
- Memory usage trend

---

## Migration Strategy

### Phased Rollout

1. **Phase 1 (Critical)** - Deploy independently, immediate risk reduction
2. **Phase 2 (Data)** - Deploy with Phase 1 or separately, no dependencies
3. **Phase 3 (I/O)** - Deploy with Phase 2 or separately
4. **Phase 4 (Memory)** - Deploy last, depends on Phase 1 task registry

### Rollback Plan

Each phase can be reverted independently. No database migrations required.

### Verification

After each phase:
1. Run full test suite
2. Deploy to staging (if available)
3. Monitor logs for anomalies
4. Verify memory usage stable over 1 hour

---

## Acceptance Criteria

### Phase 1 Complete When:
- [ ] Zero `redis.keys()` calls in codebase
- [ ] All subprocess operations have explicit timeout
- [ ] All `asyncio.create_task()` calls use task registry
- [ ] Daemon shutdown cancels all registered tasks
- [ ] Unit tests pass for all changes

### Phase 2 Complete When:
- [ ] Cache has secondary indexes for computer and status
- [ ] Session.to_dict() caches result (if applicable)
- [ ] Duplicate DB functions consolidated
- [ ] No performance regression in existing tests

### Phase 3 Complete When:
- [ ] All polling intervals use named constants
- [ ] Backoff resets on success
- [ ] psutil calls run in executor
- [ ] No blocking calls in async context

### Phase 4 Complete When:
- [ ] All state dicts are bounded
- [ ] Session close triggers cleanup
- [ ] Redis stream uses correct positioning
- [ ] Long-running memory test passes

### Full Work Item Complete When:
- [ ] All phases complete
- [ ] No regressions in existing tests
- [ ] Code review approved
- [ ] Documentation updated (if patterns are novel)

---

## Dependencies

- None (internal refactoring only)

## Estimated Complexity

- **Phase 1**: Medium (safety-critical, requires careful review)
- **Phase 2**: Medium (data structure changes, need thorough testing)
- **Phase 3**: Low (straightforward fixes)
- **Phase 4**: Low-Medium (memory patterns, need verification)

## Risk Assessment

- **Low risk**: All changes are internal refactoring
- **No API changes**: External contracts unchanged
- **Incremental**: Each phase deployable independently
- **Reversible**: No migrations, easy rollback
