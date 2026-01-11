# Code Review: data-caching-pushing

**Reviewed**: 2026-01-11
**Reviewer**: Claude Opus 4.5 (Reviewer Role)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Phase 0: Fix REST/MCP Separation | ✅ | MCPServerProtocol removed, command_handlers used directly |
| Phase 1: DaemonCache Foundation | ✅ | Cache class created with TTL, interest, notifications |
| Phase 2: REST Reads from Cache | ✅ | Endpoints merge local + cached remote data |
| Instant reads for TUI | ⚠️ | Local data instant, cache population not yet wired |
| Linting passes | ✅ | `make lint` shows 0 errors |
| Tests pass | ❌ | All REST adapter tests broken (35 errors, 5 failures) |
| Unit tests for cache | ❌ | No tests/unit/test_cache.py exists |

## Critical Issues (must fix)

### 1. [tests] All REST adapter tests are broken
- **Location**: `tests/unit/test_rest_adapter.py`
- **Description**: 35 errors from `AttributeError: 'RESTAdapter' object has no attribute 'set_mcp_server'`. Tests reference removed `set_mcp_server()` method and expect 503 status codes that no longer apply.
- **Suggested fix**:
  1. Remove `mock_mcp_server` fixture
  2. Update `rest_adapter` fixture to accept optional mock cache
  3. Replace MCP server mocks with `command_handlers` patches
  4. Remove tests expecting 503 for "no MCP server" (that concept no longer exists)
  5. Add tests verifying cache integration (merging local + cached data)

### 2. [tests] No tests for DaemonCache class
- **Location**: `tests/unit/test_cache.py` (missing)
- **Description**: The new DaemonCache class has zero test coverage. Implementation plan explicitly requires: "tests/unit/test_cache.py - TTL logic, data operations, interest management"
- **Suggested fix**: Create test file with:
  - `test_cached_item_is_stale_*` for TTL scenarios (0, negative, positive, boundary)
  - `test_get_computers_auto_expires_stale_entries`
  - `test_get_sessions_filters_by_computer`
  - `test_update_*_notifies_subscribers`
  - `test_set_interest_replaces_existing`
  - `test_notify_handles_callback_exception`

## Important Issues (should fix)

### 3. [code] import-outside-toplevel in daemon.py
- **Location**: `teleclaude/daemon.py:201-202`
- **Description**: Coding directives state "All imports at module top level (no import-outside-toplevel)". The DaemonCache import is inside `__init__`.
- **Suggested fix**: Move `from teleclaude.core.cache import DaemonCache` to top of file with other imports.

### 4. [errors] Todo fetch failures silently return empty list
- **Location**: `teleclaude/adapters/rest_adapter.py:337-342`
- **Description**: When `handle_list_todos()` fails, error is logged as WARNING but project returns with empty `todos` list. Users cannot distinguish between "no todos" and "failed to load todos".
- **Suggested fix**: Add `todos_error` field to project dict when fetch fails, or return HTTPException if todos are critical.

### 5. [code] set_interest() should copy input to prevent aliasing
- **Location**: `teleclaude/core/cache.py:269-276`
- **Description**: Coding directives say "Never mutate inputs or shared state". The method directly assigns the input set, allowing external mutation of internal state.
- **Suggested fix**: Change to `self._interest = interests.copy()`

### 6. [code] list_computers could return duplicates
- **Location**: `teleclaude/adapters/rest_adapter.py:191-221`
- **Description**: If a cached computer has the same name as local computer (misconfiguration), duplicates appear in response.
- **Suggested fix**: Filter out local computer name when adding cached computers: `if comp["name"] == local_name: continue`

### 7. [code] Inconsistent stale entry handling
- **Location**: `teleclaude/core/cache.py:129-165`
- **Description**: `get_computers()` auto-expires stale entries and logs. `get_projects()` silently skips stale entries without removal or logging. Inconsistent behavior.
- **Suggested fix**: Choose one approach (auto-expire or filter) and apply consistently to both methods.

### 8. [errors] Subscriber callback failures swallowed
- **Location**: `teleclaude/core/cache.py:325-329`
- **Description**: When a subscriber callback fails, error is logged but calling code never knows. No mechanism to identify or remove misbehaving subscribers.
- **Suggested fix**: Consider tracking failed callbacks and auto-unsubscribing after N failures, or include callback identity in error logs for debugging.

## Suggestions (nice to have)

### 9. [types] Callback type too loose
- **Location**: `teleclaude/core/cache.py:75`
- **Description**: `Callable[[str, object], None]` loses type safety. Event names are stringly-typed, data is untyped.
- **Suggested fix**: Consider discriminated union events for type-safe notifications.

### 10. [code] TTL values are magic numbers
- **Location**: `teleclaude/core/cache.py` (scattered throughout)
- **Description**: TTL values (60, 300) are inline magic numbers in method bodies.
- **Suggested fix**: Extract to class constants: `COMPUTER_TTL = 60`, `PROJECT_TTL = 300`, etc.

### 11. [types] Status fields should be Literal types
- **Location**: `teleclaude/mcp/types.py`, `teleclaude/core/command_handlers.py`
- **Description**: Status fields like `status: str` should be `Literal["online", "offline"]` or similar.
- **Suggested fix**: Add Literal type constraints to status fields in TypedDicts.

## Strengths

- Clean architectural separation: REST adapter no longer depends on MCP server
- DaemonCache design is appropriate for the domain (computers, projects, sessions, todos)
- Good logging at key execution points
- Proper error handling with HTTPException in REST endpoints
- Generic CachedItem[T] provides type-safe caching
- Lint passes with 0 errors

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first

### Priority fixes:
1. **Fix broken tests in test_rest_adapter.py** - Tests are essential for merge
2. **Add tests for DaemonCache** - Core feature requires test coverage
3. **Move import to top level in daemon.py** - Coding directive violation
4. **Fix set_interest() aliasing** - Potential for external mutation of internal state
