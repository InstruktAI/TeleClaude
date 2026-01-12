# Code Review: cache-deferreds

**Reviewed**: 2026-01-12
**Reviewer**: Claude Opus 4.5 (code-reviewer)
**Branch**: cache-deferreds
**Files Changed**: teleclaude/adapters/redis_adapter.py, teleclaude/adapters/rest_adapter.py

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Computers from heartbeats (60s TTL) | ✅ | `cache.update_computer()` called in `_get_interested_computers()` |
| Remote projects pull-once (5 min TTL) | ✅ | `pull_remote_projects()` triggered on stale check in REST endpoint |
| Initial session pull on interest | ✅ | `_pull_initial_sessions()` called when interest first registered |
| Remote todos pull-once (5 min TTL) | ✅ | `pull_remote_todos()` triggered on stale check in REST endpoint |
| Manual refresh re-fetch | ⚠️ | NOT IMPLEMENTED - Phase 5 tasks unchecked in implementation-plan.md |
| TTL-based auto-refresh | ⚠️ | NOT IMPLEMENTED - Phase 6 tasks unchecked in implementation-plan.md |

## Critical Issues (must fix)

### [tests] Missing Test Coverage for All New Methods
**Severity**: Critical

The implementation adds 4 new major methods but zero unit tests:
- `_pull_initial_sessions()` - redis_adapter.py:1273
- `pull_remote_projects(computer)` - redis_adapter.py:1332
- `pull_remote_todos(computer, project_path)` - redis_adapter.py:1386
- Heartbeat → cache.update_computer() flow - redis_adapter.py:1238-1255

**Impact**: Silent failures in production. Cache population could silently fail without any test catching regressions.

**Suggested fix**: Add unit tests covering:
- Happy path (successful pull populates cache)
- Timeout handling (continues to next computer)
- Malformed response handling (logs warning, skips)
- Error status handling (logs warning, skips)
- Empty cache case (no computers to pull from)

---

### [errors] Untracked Background Tasks with Silent Failures
**Location**: `rest_adapter.py:269-270`, `rest_adapter.py:384-385`

```python
else:
    # Fallback: create untracked task
    asyncio.create_task(redis_adapter.pull_remote_projects(comp_name))
```

**Problem**: If `pull_remote_projects()` or `pull_remote_todos()` fail in the background task, the exception is silently swallowed by asyncio. No logging, no error visibility.

**Suggested fix**: Add exception callback:
```python
task = asyncio.create_task(redis_adapter.pull_remote_projects(comp_name))
task.add_done_callback(lambda t: logger.error("Pull failed: %s", t.exception()) if t.exception() else None)
```

## Important Issues (should fix)

### [code] Import Statements Inside Function Bodies
**Location**: `redis_adapter.py:1240`, `redis_adapter.py:1371`, `redis_adapter.py:1426`

```python
if self.cache:
    from teleclaude.mcp.types import ComputerInfo
```

**Problem**: Testing directives explicitly list "Import-outside-toplevel violations" as lint violations that must be fixed before committing.

**Suggested fix**: Move imports to module top level with other imports.

---

### [code] Redundant Exception Catching Pattern
**Location**: `redis_adapter.py:1328`, `redis_adapter.py:1383`, `redis_adapter.py:1438`

```python
except (TimeoutError, Exception) as e:
```

**Problem**: `TimeoutError` is a subclass of `Exception`, so catching both is redundant. This pattern masks intent and catches ALL exceptions including programming errors that should propagate.

**Suggested fix**: Either catch specific exceptions or just `Exception`:
```python
except Exception as e:  # If all exceptions should be caught
# OR
except (TimeoutError, json.JSONDecodeError) as e:  # If only specific ones
```

---

### [errors] Cache None Early Returns Without Logging
**Location**: `redis_adapter.py:1278`, `redis_adapter.py:1338`, `redis_adapter.py:1393`

```python
if not self.cache:
    return  # Silent exit, no logging
```

**Problem**: If cache is None, critical operations silently skip without any warning. Users/operators have no visibility into why remote data isn't appearing.

**Suggested fix**: Add warning log:
```python
if not self.cache:
    logger.warning("Cache unavailable, skipping %s", operation_name)
    return
```

---

### [types] Unsafe `cast()` Without Validation
**Location**: `redis_adapter.py:1323`, `redis_adapter.py:1376`, `redis_adapter.py:1431`

```python
session: "SessionInfo" = cast("SessionInfo", session_obj)
```

**Problem**: Cast assumes dict has all required TypedDict fields without verification. If remote returns malformed data (missing fields, wrong types), invalid data enters the cache.

**Suggested fix**: Implement validation before cast:
```python
def validate_session_info(obj: dict[str, object]) -> SessionInfo:
    required_fields = ["session_id", "computer", "status", ...]
    for field in required_fields:
        if field not in obj:
            raise ValueError(f"Missing field: {field}")
    return cast(SessionInfo, obj)
```

---

### [tests] REST Adapter Tests Don't Verify Background Pull Spawning
**Location**: `tests/unit/test_rest_adapter.py`

**Problem**: Existing REST adapter tests mock the cache but don't verify:
- `is_stale()` was called
- Background pull was spawned via `task_registry.spawn()`

Tests pass even if staleness check code is deleted.

**Suggested fix**: Add tests that:
- Mock redis adapter and verify `pull_remote_projects()` was spawned when stale
- Verify `pull_remote_todos()` was spawned when stale
- Verify no pull when fresh (is_stale returns False)

## Suggestions (nice to have)

### [code] String Literals in Cast
**Location**: `redis_adapter.py:1323`, `redis_adapter.py:1376`, `redis_adapter.py:1431`

```python
cast("SessionInfo", session_obj)  # String literal
```

Using string literals in `cast()` defeats type checker verification. Use actual type:
```python
cast(SessionInfo, session_obj)  # Actual type
```

---

### [code] Staleness Check Key Pattern
**Location**: `rest_adapter.py:259`

```python
cache_key = f"{comp_name}:*"  # Wildcard pattern
```

The `is_stale()` check uses wildcard key pattern. Verify this matches how cache stores/retrieves project data. If keys are stored as `comp_name:project_path`, the wildcard may not work as expected with `is_stale()`.

## Strengths

- **Clear separation of concerns**: Pull methods are well-isolated and single-purpose
- **Good logging**: INFO for significant events, DEBUG for routine operations, WARNING for recoverable issues
- **Proper type guards**: `isinstance()` checks before accessing dict fields
- **Interest-driven behavior**: Initial pull only happens when cache registers interest, preventing unnecessary work
- **Non-blocking design**: REST endpoints spawn background pulls and return immediately

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first
**[ ] APPROVE** - Ready to merge

### Priority Fixes Before Approval:

1. **Add unit tests** for `_pull_initial_sessions()`, `pull_remote_projects()`, `pull_remote_todos()`, and heartbeat → cache flow
2. **Add exception callbacks** to untracked background tasks in REST adapter
3. **Move imports** to module top level (lint violation)
4. **Simplify exception catching** - remove redundant `TimeoutError` from `(TimeoutError, Exception)`
5. **Add warning logs** for cache None early returns

### Notes:

- Implementation plan shows Phase 5 (Manual Refresh) and Phase 6 (TTL Auto-Refresh) are NOT IMPLEMENTED
- These were marked as unchecked in the plan, so this is expected incomplete work
- Core Phases 1-4 are implemented as designed
