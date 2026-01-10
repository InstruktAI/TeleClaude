# Code Review: terminal-adapter-refactor (Third Review)

**Reviewed**: 2026-01-10
**Reviewer**: Claude Opus 4.5 (Orchestrated Review with sub-agents)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Rename TerminalAdapter to RESTAdapter | ✅ | Complete - `ADAPTER_KEY = "rest"` at line 47 |
| R2: REST Adapter routes through AdapterClient | ✅ | Complete - `handle_event()` used for all endpoints |
| R3: Resume commands | ⏳ | Phase 2 - Not in scope for this review |
| R4: Database composite lookup | ⏳ | Phase 2 - Not in scope for this review |
| R5: telec CLI updates | ⏳ | Phase 3 - Not in scope for this review |
| R6: TUI auto-focus | ⏳ | Phase 3 - Not in scope for this review |
| R7: Consistent command experience | ✅ | Foundation laid |
| D1: Rename "terminal" to "rest" origin_adapter | ✅ | Complete - `terminal_sessions.py` lines 74, 121 use `'rest'` |

## Critical Issues (must fix)

### 1. [code] REST adapter expects raw data but receives envelope from AdapterClient

**Location**: `rest_adapter.py:93-96, 183-195, 202-214`

**Description**: The REST adapter checks `isinstance(result, list)` on the return from `client.handle_event()`, expecting raw list data. However, `AdapterClient.handle_event()` returns an envelope:

```python
# adapter_client.py line 900 (_dispatch method)
return {"status": "success", "data": result}
```

The REST adapter code:
```python
# rest_adapter.py lines 92-96
result = await self.client.handle_event(...)
if isinstance(result, list):  # FALSE! result is {"status": "success", "data": [...]}
    return result
logger.error("list_sessions returned non-list result: %s", type(result).__name__)
raise HTTPException(status_code=500, detail="Internal error: unexpected handler result type")
```

**Impact**:
- **ALL production calls** to `/sessions`, `/computers`, `/projects` will fail with HTTP 500
- Tests pass because they mock `handle_event` to return raw lists instead of the actual envelope
- Users see "Internal error: unexpected handler result type" with no sessions returned

**Affected endpoints**:
- `GET /sessions` (list_sessions)
- `GET /computers` (list_computers)
- `GET /projects` (list_projects)

**Fix required**:
```python
# Unwrap envelope from handle_event
if isinstance(result, dict) and result.get("status") == "success":
    data = result.get("data")
    if isinstance(data, list):
        return data
raise HTTPException(status_code=500, detail="Handler error or unexpected result type")
```

**Also fix tests** to return proper envelopes:
```python
mock_adapter_client.handle_event.return_value = {"status": "success", "data": [...]}
```

## Important Issues (should fix)

### 2. [code] Hardcoded socket path differs from MCP pattern

**Location**: `rest_adapter.py:297`

**Description**: The REST API socket path `/tmp/teleclaude-api.sock` is hardcoded, while MCP uses `MCP_SOCKET_PATH` from `teleclaude/constants.py`.

**Suggested fix**: Add `REST_SOCKET_PATH` to `teleclaude/constants.py` for consistency.

### 3. [code] Unused `computer` parameter in endpoints

**Location**: `rest_adapter.py:147-160, 164-177`

**Description**: The `computer` query parameter is required but explicitly unused with `# noqa: ARG001`. It's marked "for API consistency" but adds confusion.

**Suggested fix**: Either use it to validate session ownership, or make it optional with documentation.

### 4. [types] Potential type duplication - EndSessionResult

**Location**: `rest_adapter.py:28-33`

**Description**: `EndSessionResult` TypedDict may already exist in `teleclaude/mcp/types.py`. Duplicates can drift over time.

**Suggested fix**: Check if it exists in mcp/types.py and import from there if so.

### 5. [tests] Error path tests missing

**Description**: REST adapter tests cover happy paths but miss:
- `end_session` when MCP throws an exception
- `create_session` when handler returns error envelope
- `send_message` when handler fails

### 6. [tests] Tests mock incorrect envelope format

**Description**: All test mocks return raw data instead of the envelope that `handle_event` actually returns. This masks the critical bug in issue #1.

Example:
```python
# Current (WRONG)
mock_adapter_client.handle_event.return_value = [{"session_id": "sess-1"}]

# Should be
mock_adapter_client.handle_event.return_value = {"status": "success", "data": [{"session_id": "sess-1"}]}
```

## Suggestions (nice to have)

### 7. [types] Add min_length constraints to Pydantic models

**Location**: `rest_models.py`

- `computer: str` and `project_dir: str` accept empty strings
- `message: str` in SendMessageRequest accepts empty string

**Suggested fix**:
```python
from pydantic import Field
computer: str = Field(..., min_length=1)
project_dir: str = Field(..., min_length=1)
message: str = Field(..., min_length=1)
```

### 8. [types] Session dataclass uses str instead of enums

**Location**: `core/models.py:273-274`

**Description**: `Session.active_agent` and `Session.thinking_mode` are `Optional[str]` but `AgentName` and `ThinkingMode` enums exist. This creates inconsistency between REST models (which use `Literal`) and internal models.

## Strengths

1. **Clean architectural separation** - RESTAdapter properly routes through AdapterClient's event system
2. **Correct adapter key change** - `ADAPTER_KEY = "rest"` properly set
3. **Proper error handling fixed** - Uses HTTPException with 500/503 codes (from previous review)
4. **Literal types for enums** - `CreateSessionRequest` uses `Literal["claude", "gemini", "codex"]`
5. **MCPServerProtocol** - Clean protocol typing for dependency injection
6. **Async file I/O** - `list_todos` uses `asyncio.to_thread()` (from previous review)
7. **MCP server wiring** - Daemon correctly wires MCP server for end_session operation
8. **Comprehensive test coverage** - 650 tests passing, 21 REST adapter tests
9. **All lint/type checks pass** - ruff, pyright, mypy all clean

## Test Results

- **650/650 unit tests passing** ⚠️ (but tests don't exercise real code path for list endpoints)
- **Lint: passing** (0 errors)
- **Type check: passing** (0 errors)

## Verdict

**[x] REQUEST CHANGES** - Fix critical issue before merge

### Priority fixes:
1. **CRITICAL**: Fix envelope unwrapping in REST adapter for list endpoints
2. **CRITICAL**: Update tests to use correct envelope format
3. **IMPORTANT**: Consider adding the other suggestions post-merge

---

## Previous Review Fixes (commits bea06ca through 4dfb2fb)

All issues from previous reviews have been addressed:

| Issue | Status |
|-------|--------|
| Forward reference breaks FastAPI body detection | ✅ Fixed |
| Silent `return []` fallbacks | ✅ Fixed - now raises HTTP 500 |
| HTTP 200 for error conditions | ✅ Fixed - uses 503/500 |
| Loose string types for enums | ✅ Fixed - uses Literal types |
| EndSessionResult.status allows any string | ✅ Fixed - `Literal["success", "error"]` |
| Synchronous file I/O | ✅ Fixed - uses `asyncio.to_thread()` |
| Column index bug in terminal_sessions.py | ✅ Fixed |
| No unit tests for REST adapter | ✅ Fixed - 21 tests |
| mcp_server typed as object | ✅ Fixed - MCPServerProtocol |

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Critical: REST adapter envelope unwrapping bug | Fixed list_sessions, list_computers, list_projects to unwrap envelope properly | fa198c8 |
| Critical: Tests mock incorrect envelope format | Updated all tests to return correct envelope: `{"status": "success", "data": [...]}` | fa198c8 |
| Important: Hardcoded socket path | Added REST_SOCKET_PATH constant to constants.py | a79832d |
| Important: Unused computer parameter | Made computer parameter optional with documentation | a79832d |
| Suggestion: EndSessionResult type duplication | Verified - REST adapter version has stricter Literal type, keeping as-is | - |
