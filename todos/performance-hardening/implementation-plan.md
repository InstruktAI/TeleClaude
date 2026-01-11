# Implementation Plan: Performance Hardening

## Overview

Four-phase infrastructure hardening addressing async safety, data efficiency, I/O resilience, and memory management. Each phase is independently deployable and testable.

---

## Phase 1: Critical Safety

### 1.1 Redis KEYS → SCAN Migration

- [x] Create `teleclaude/core/redis_utils.py` with `async def scan_keys(redis, pattern)` helper
- [x] Replace `redis.keys()` call #1 in `redis_adapter.py` with `scan_keys()`
- [x] Replace `redis.keys()` call #2 in `redis_adapter.py` with `scan_keys()`
- [x] Replace `redis.keys()` call #3 in `redis_adapter.py` with `scan_keys()`
- [x] Add unit test for `scan_keys()` cursor iteration
- [x] Verify: `grep -r "\.keys(" teleclaude/` returns zero Redis key calls

### 1.2 Subprocess Timeout Enforcement

- [x] Define timeout constants at top of `terminal_bridge.py`: `SUBPROCESS_TIMEOUT_DEFAULT = 30.0`
- [x] Create helper `async def wait_with_timeout(process, timeout)` that kills on timeout
- [x] Audit and fix `wait()` call in `_run_tmux_command()`
- [x] Audit and fix `wait()` call in `send_keys()`
- [x] Audit and fix `wait()` call in `capture_pane()`
- [x] Audit and fix remaining `wait()`/`communicate()` calls (expect 5+ more)
- [x] Add unit test: mock hanging process, verify timeout triggers kill
- [x] Verify: grep for `\.wait\(\)` without timeout wrapper returns zero

### 1.3 Task Lifecycle Management

- [ ] Create `teleclaude/core/task_registry.py` with `TaskRegistry` class
- [ ] Implement `spawn(coro, name)` method that tracks tasks
- [ ] Implement `shutdown(timeout)` method that cancels all tasks
- [ ] Integrate registry into `Daemon.__init__()`
- [ ] Replace fire-and-forget in `rest_adapter.py:_on_cache_change()` with registry
- [ ] Replace fire-and-forget in `redis_adapter.py` (event dispatch) with registry
- [ ] Call `registry.shutdown()` in daemon shutdown path
- [ ] Add unit test: spawn tasks, call shutdown, verify all cancelled
- [ ] Verify: `grep "create_task" teleclaude/` - all should use registry or be justified

---

## Phase 2: Data Layer Efficiency

### 2.1 Cache Index Structures

- [ ] Add `_sessions_by_computer: dict[str, set[str]]` to `CentralCache`
- [ ] Add `_sessions_by_status: dict[str, set[str]]` to `CentralCache`
- [ ] Update `set_session()` to maintain indexes
- [ ] Update `invalidate_session()` to clean indexes
- [ ] Add `get_sessions_for_computer(computer)` using index
- [ ] Add `get_sessions_by_status(status)` using index
- [ ] Update callers of `get_sessions()` that filter by computer to use indexed method
- [ ] Add unit test: verify O(1) behavior (timing or call counting)

### 2.2 Session Serialization Optimization

- [ ] Analyze Session dataclass - confirm it's frozen (immutable)
- [ ] If frozen: add `@functools.lru_cache` to `to_dict()` method
- [ ] If mutable: add `_cached_dict` field with invalidation on mutation
- [ ] Add unit test: call `to_dict()` twice, verify second call returns cached

### 2.3 Database Function Consolidation

- [ ] Identify duplicate: `get_all_sessions()` vs `get_active_sessions()` in `db.py`
- [ ] Create unified `get_sessions(status_filter=None)` method
- [ ] Update all callers to use unified method
- [ ] Remove duplicate methods
- [ ] Verify tests still pass

---

## Phase 3: I/O Resilience

### 3.1 Configurable Polling Intervals

- [ ] Add constants to `output_poller.py`: `POLL_INTERVAL_DEFAULT`, `POLL_INTERVAL_MIN`, `POLL_INTERVAL_MAX`
- [ ] Replace hard-coded `sleep(1.0)` with configurable interval
- [ ] Add constants to `terminal_bridge.py` for any hard-coded sleeps
- [ ] Replace hard-coded sleeps with constants

### 3.2 Backoff Reset Logic

- [ ] Locate exponential backoff in `output_poller.py`
- [ ] Add `success()` method that resets to initial value
- [ ] Call `success()` after successful poll
- [ ] Add unit test: simulate failures then success, verify reset

### 3.3 Async-Safe System Stats

- [ ] Locate `psutil.cpu_percent(interval=0.1)` in `terminal_bridge.py`
- [ ] Wrap in `loop.run_in_executor(None, ...)`
- [ ] Verify memory stats remain synchronous (they're non-blocking)
- [ ] Add unit test or manual verification: event loop not blocked

---

## Phase 4: Memory Management

### 4.1 Bounded State Dictionaries

- [ ] Create `teleclaude/core/bounded_dict.py` with `BoundedDict(max_size)` class
- [ ] Replace `_last_stop_time` dict in `adapter_client.py` with `BoundedDict`
- [ ] Replace `_prev_state` dict in TUI views with `BoundedDict`
- [ ] Replace `_active_field` dict in TUI views with `BoundedDict`
- [ ] Add unit test: insert beyond max_size, verify oldest evicted

### 4.2 Session Cleanup on Close

- [ ] Add `on_session_closed(session_id)` method to `AdapterClient`
- [ ] Clean `_listeners` dict entry
- [ ] Clean `_last_stop_time` dict entry
- [ ] Call cleanup when session transitions to terminal state
- [ ] Add unit test: close session, verify dicts cleaned

### 4.3 Redis Stream Positioning

- [ ] Locate `xread(..., streams={stream: b"0"})` in `redis_adapter.py`
- [ ] Change to `b"$"` for "only new messages" OR implement last-seen tracking
- [ ] Add unit test: simulate reconnect, verify no history replay

---

## Verification

### Per-Phase Verification

After each phase:
- [ ] Run `make test` - all tests pass
- [ ] Run `make lint` - no violations
- [ ] Restart daemon, verify no startup errors
- [ ] Monitor logs for 5 minutes, no anomalies

### Final Verification

- [ ] All phases complete
- [ ] Full test suite passes
- [ ] Memory usage stable over extended run (manual check)
- [ ] No performance regressions

---

## Files to Modify

| File | Phases |
|------|--------|
| `teleclaude/adapters/redis_adapter.py` | 1.1, 1.3, 4.3 |
| `teleclaude/core/terminal_bridge.py` | 1.2, 3.1, 3.3 |
| `teleclaude/adapters/rest_adapter.py` | 1.3 |
| `teleclaude/core/cache.py` | 2.1 |
| `teleclaude/core/models.py` | 2.2 |
| `teleclaude/core/db.py` | 2.3 |
| `teleclaude/core/output_poller.py` | 3.1, 3.2 |
| `teleclaude/core/adapter_client.py` | 4.1, 4.2 |
| `teleclaude/cli/tui/views/*.py` | 4.1 |

## New Files

| File | Purpose |
|------|---------|
| `teleclaude/core/redis_utils.py` | SCAN helper |
| `teleclaude/core/task_registry.py` | Task lifecycle management |
| `teleclaude/core/bounded_dict.py` | Memory-bounded dict |
