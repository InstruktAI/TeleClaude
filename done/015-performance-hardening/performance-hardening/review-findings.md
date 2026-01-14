# Code Review: performance-hardening

**Reviewed**: 2026-01-12
**Reviewer**: Claude Opus 4.5 (prime-reviewer) - Final review

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| 1.1 Redis KEYS → SCAN Migration | ✅ | `scan_keys()` properly iterates cursor until 0; all 3 occurrences replaced |
| 1.2 Subprocess Timeout Enforcement | ✅ | `wait_with_timeout()` and `communicate_with_timeout()` implemented; all subprocess operations use them |
| 1.3 Task Lifecycle Management | ✅ | `TaskRegistry` implemented; integrated into daemon, redis_adapter, rest_adapter; shutdown calls `registry.shutdown()` |
| Phase 1 Acceptance Criteria | ✅ | Zero `redis.keys()` calls; all subprocess ops have timeouts; background tasks use registry |

## Previous Issues Resolution

All previously identified issues have been fixed and verified:

| Issue | Status | Verification |
|-------|--------|--------------|
| Infinite recursion in timeout handlers | ✅ FIXED | Uses direct `asyncio.wait_for()` |
| Task exceptions never surfaced | ✅ FIXED | Logs exceptions with `exc_info=exc` |
| scan_keys errors documented | ✅ FIXED | Docstrings explain graceful degradation |
| Untracked task fallback | ✅ FIXED | Adds `_log_task_exception` callback |
| SubprocessTimeoutError structured data | ✅ FIXED | Has operation, timeout, pid attributes |
| Test mocks keys instead of scan | ✅ FIXED | All tests mock `scan` correctly |
| TypeVar for spawn() return type | ✅ FIXED | Uses `TypeVar("T")` for type inference |

## Critical Issues (must fix)

None identified. All critical issues from previous reviews have been addressed.

## Important Issues (should fix)

### 1. [code] `terminal_bridge.py` - Multiple functions use `print()` instead of `logger.error()`

**Description:** 13 functions in terminal_bridge.py use `print()` for error reporting instead of the configured logger. In daemon mode, these errors are completely invisible.

**Affected functions:** `create_tmux_session` (line 290), `send_escape` (696), `send_ctrl_key` (720), `send_tab` (741), `send_shift_tab` (769), `send_backspace` (797), `send_enter` (818), `send_arrow_key` (854), `kill_session` (911), `list_tmux_sessions` (935), `get_session_pane_id` (1113), `start_pipe_pane` (1135), `stop_pipe_pane` (1156)

**Note:** This is pre-existing technical debt, not introduced by this PR. Should be addressed in a separate cleanup PR.

### 2. [code] `terminal_bridge.py:17` - Mixed typing styles

**Description:** File imports old-style `Dict`, `List`, `Optional` from typing but also uses modern `str | None` syntax. Per coding directives, all code should use modern syntax.

**Suggested fix:** Replace `Optional[X]` with `X | None`, `Dict[K, V]` with `dict[K, V]`, `List[T]` with `list[T]`.

**Note:** This is pre-existing technical debt. The new code (SubprocessTimeoutError, timeout helpers) correctly uses modern syntax.

### 3. [types] `redis_adapter.py:617,1214` - Type annotation uses `object` instead of `list[bytes]`

**Description:** Call sites annotate `keys: object` but `scan_keys()` returns `list[bytes]`. This throws away type information.

```python
keys: object = await scan_keys(...)  # Should be: keys: list[bytes]
```

**Note:** This is pre-existing code at those call sites. The scan_keys function itself has correct typing.

### 4. [tests] Missing test for process termination failure after SIGKILL

**Description:** The error path where `process.wait()` times out AFTER `kill()` (lines 87-88, 130-131 in terminal_bridge.py) is not tested. This is a real-world scenario with zombie processes.

### 5. [tests] Missing test for Redis connection errors in `scan_keys`

**Description:** The `scan_keys` function can raise exceptions if Redis is unavailable. No error handling test exists in `test_redis_utils.py`.

## Suggestions (nice to have)

### 6. [error-handling] `terminal_bridge.py:176-188` - Silent OSError swallowing in temp dir setup

**Description:** `_prepare_session_tmp_dir` catches OSError silently for rmtree, chmod, and file write operations. While best-effort cleanup is reasonable, DEBUG-level logging would aid troubleshooting.

### 7. [error-handling] `redis_adapter.py:1144-1150` - Lambda callback with incomplete exception logging

**Description:** The lambda callback for push event tasks logs exceptions but doesn't include `exc_info=` for stack traces. The `_log_task_exception` method pattern should be used instead.

### 8. [tests] Missing test for TaskRegistry shutdown timeout warning logging

**Description:** `test_shutdown_logs_pending_tasks_on_timeout` exists but doesn't verify the warning was actually logged.

### 9. [error-handling] `terminal_bridge.py:1086` - Silent exception in `is_pane_dead`

**Description:** The `except Exception` block catches all exceptions and returns `False` without any logging.

## Out of Scope Findings

The following issues were identified but are pre-existing technical debt, not introduced by this PR:

1. **terminal_bridge.py print() usage** - 13 functions use print() instead of logger
2. **Old-style typing imports** - Legacy `Dict`, `List`, `Optional` throughout terminal_bridge.py
3. **rest_adapter.py:511** - Server startup task not tracked by TaskRegistry
4. **Untracked tasks in other files** - telegram_adapter.py, computer_registry.py, codex_watcher.py, polling_coordinator.py

These should be addressed in separate PRs to maintain atomic changes.

## Strengths

1. **Clean architecture**: New modules (`redis_utils.py`, `task_registry.py`) have single responsibilities and excellent encapsulation
2. **Proper cursor iteration**: `scan_keys()` correctly iterates until cursor == 0
3. **Comprehensive timeout coverage**: All subprocess operations use timeout wrappers
4. **TaskRegistry design**: Done callback pattern elegantly handles auto-cleanup and exception logging
5. **Graceful shutdown**: `registry.shutdown()` cancels all tasks with timeout
6. **Good test coverage**: All new components have comprehensive unit tests (736 tests passing)
7. **Follows project patterns**: Functions over classes, explicit typing, proper logging
8. **Excellent type annotations**: Modern Python syntax (`int | None`, TypeVar for generic returns)
9. **Good documentation**: Docstrings explain graceful degradation behavior
10. **All lints pass**: 0 errors from ruff, pyright, mypy

## Verdict

**[x] APPROVE** - Ready to merge
**[ ] REQUEST CHANGES** - Fix critical/important issues first

### Rationale

The Phase 1 implementation fully meets all functional requirements. All previously identified critical issues have been properly addressed and verified:

- Zero `redis.keys()` calls remain in codebase
- All subprocess operations have explicit timeouts
- Background tasks use TaskRegistry for lifecycle management
- Daemon shutdown properly cancels all registered tasks
- 736 unit tests pass
- All lint checks pass

The remaining issues are either:
1. **Pre-existing technical debt** not introduced by this PR (print() usage, old typing imports)
2. **Suggestions** for future improvement (test coverage gaps, minor logging enhancements)

None of the issues are blockers for the core Phase 1 safety improvements being merged. The code is production-ready and significantly improves async safety, subprocess resilience, and task lifecycle management.
