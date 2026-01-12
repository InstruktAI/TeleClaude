# Code Review: cache-deferreds

**Reviewed**: 2026-01-12
**Reviewer**: Claude Opus 4.5 (prime-reviewer)
**Branch**: cache-deferreds
**Commits**: 12 commits (4e5b5aa → 95cca19)
**Files Changed**: teleclaude/adapters/redis_adapter.py, teleclaude/adapters/rest_adapter.py, tests/unit/test_redis_adapter_cache_pull.py

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

_None identified._

## Important Issues (should fix)

### [tests] Missing test for `pull_remote_todos` timeout handling
**Location**: `tests/unit/test_redis_adapter_cache_pull.py`

Tests cover timeout for `_pull_initial_sessions` and `pull_remote_projects`, but **not for `pull_remote_todos`**. This asymmetry leaves a gap in error handling coverage.

**Suggested fix**: Add `test_pull_remote_todos_timeout()` following the same pattern as `test_pull_remote_projects_timeout()`.

---

### [tests] REST adapter background pull spawning is untested
**Location**: `teleclaude/adapters/rest_adapter.py:262-291, 380-411`

The code spawns background tasks via `task_registry.spawn()` or `asyncio.create_task()` fallback. This critical async machinery has **zero test coverage**:
- No verification that staleness check triggers pulls
- No verification that exception callbacks work in fallback path

**Suggested fix**: Add integration tests verifying:
- `pull_remote_projects()` spawned when `is_stale()` returns True
- `pull_remote_todos()` spawned when stale
- No pull triggered when fresh (is_stale returns False)

---

### [types] Unsafe `cast()` without validation
**Location**: `redis_adapter.py:1324, 1376, 1430`

```python
session: "SessionInfo" = cast("SessionInfo", session_obj)
```

The code checks `isinstance(session_obj, dict)` then casts, but does NOT validate:
- All required keys exist (`session_id`, `origin_adapter`, etc.)
- Values have correct types
- Values satisfy semantic constraints

**Impact**: Malformed data from remote computers enters cache and propagates.

**Suggested fix**: Add TypeGuard validation functions:
```python
def is_session_info(obj: object) -> TypeGuard[SessionInfo]:
    if not isinstance(obj, dict):
        return False
    required = {"session_id", "origin_adapter", "title", ...}
    return required <= obj.keys()
```

---

### [tests] Duplicate `@pytest.mark.unit` decorator
**Location**: `tests/unit/test_redis_adapter_cache_pull.py:28-29`

```python
@pytest.mark.unit
@pytest.mark.unit  # DUPLICATE
@pytest.mark.asyncio
```

Minor code quality issue - harmless but should be cleaned up.

**Suggested fix**: Remove the duplicate marker on line 29.

## Suggestions (nice to have)

### [code] Cache key wildcard pattern may be semantically misleading
**Location**: `rest_adapter.py:274`

```python
cache_key = f"{comp_name}:*"  # Wildcard pattern
```

The `is_stale()` check uses wildcard key `{comp_name}:*`. If cache stores keys as `{computer}:{path}`, the wildcard may not match correctly, causing staleness to always return True (not found = stale).

**Note**: This may be intentional "always refresh" semantics. Verify behavior matches intent.

---

### [types] String literal casts instead of direct type references
**Location**: `redis_adapter.py:1324, 1376, 1430`

```python
cast("SessionInfo", session_obj)  # String literal
```

Using string literals in `cast()` obscures types. Since imports exist, use direct type:
```python
cast(SessionInfo, session_obj)  # Direct reference
```

---

### [tests] Missing symmetric test coverage
**Location**: `tests/unit/test_redis_adapter_cache_pull.py`

`_pull_initial_sessions` has comprehensive tests (timeout, malformed, error status, empty). But `pull_remote_projects` and `pull_remote_todos` are missing:
- Error status response tests
- Malformed JSON tests
- Invalid `data` type (non-list) tests

Low priority since the code paths are nearly identical.

## Strengths

- **Clear separation of concerns**: Pull methods are well-isolated and single-purpose
- **Good logging**: INFO for significant events, DEBUG for routine, WARNING for recoverable issues
- **Proper type guards**: `isinstance()` checks before accessing dict fields
- **Interest-driven behavior**: Initial pull only happens when cache registers interest
- **Non-blocking design**: REST endpoints spawn background pulls and return immediately
- **Exception callbacks**: Untracked asyncio tasks have proper error logging callbacks
- **Comprehensive tests**: 12 unit tests covering happy paths and error scenarios for main methods
- **Previous review fixes applied**: All critical issues from first review have been addressed

## Verification

- **Tests**: All 12 tests pass (`make test-unit`)
- **Lint**: All checks pass (pylint, mypy, pyright, ruff)
- **Build state**: `state.json` shows build complete

## Verdict

**[x] APPROVE** - Ready to merge
**[ ] REQUEST CHANGES** - Fix critical/important issues first

### Rationale

All requirements in scope (Phases 1-4) are implemented correctly. The "important" issues identified are:
1. **Missing tests** - Gaps exist but core functionality is well-tested
2. **Unsafe casts** - TypedDict casts are common pattern; validation would improve robustness but isn't blocking
3. **Duplicate marker** - Trivial cleanup

None of these rise to "must fix before merge" level. The implementation is solid, well-tested, and follows project patterns. Phase 5-6 (manual refresh, TTL auto-refresh) were explicitly marked as out of scope in the implementation plan.

### Recommended Follow-up Work

1. Add `test_pull_remote_todos_timeout()` for symmetric coverage
2. Consider adding TypeGuard validation for remote data in a future hardening pass
3. Implement Phase 5-6 when prioritized
