# Code Review: terminal-adapter-refactor (Second Review)

**Reviewed**: 2026-01-10
**Reviewer**: Claude Opus 4.5

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Rename TerminalAdapter to RESTAdapter | ✅ | Complete - ADAPTER_KEY = "rest" |
| R2: REST Adapter routes through AdapterClient | ✅ | Complete - handle_event() used for all endpoints |
| R3: Resume commands | ⏳ | Phase 2 - Not yet implemented |
| R4: Database composite lookup | ⏳ | Phase 2 - Not yet implemented |
| R5: telec CLI updates | ⏳ | Phase 3 - Not yet implemented |
| R6: TUI auto-focus | ⏳ | Phase 3 - Not yet implemented |
| R7: Consistent command experience | ✅ | Foundation laid |
| D1: Rename "terminal" to "rest" origin_adapter | ✅ | Complete - terminal_sessions.py and all test files updated |

## Critical Issues (must fix)

### 1. [code] `rest_adapter.py:7` - Forward reference annotation breaks FastAPI body detection

**Description:** The `from __future__ import annotations` (PEP 563) makes ALL type annotations strings. When `CreateSessionRequest` and `SendMessageRequest` are imported inside `_setup_routes()` (lines 72-75), FastAPI cannot resolve these string annotations because the classes exist in the function's local scope, not the module scope. FastAPI falls back to treating `request` as a query parameter instead of a body.

**Impact:** 4 tests failing with 422 validation errors:
- `test_create_session_success`
- `test_create_session_derives_title_from_message`
- `test_create_session_defaults_title_to_untitled`
- `test_send_message_success`

**Suggested fix:** Move imports to module level:
```python
# At top of rest_adapter.py (after other imports)
from teleclaude.adapters.rest_models import CreateSessionRequest, SendMessageRequest
```
Then remove the import from inside `_setup_routes()`.

## Important Issues (should fix)

### 2. [errors] `rest_adapter.py:97-100,196-199,215-218` - Silent fallback to empty list on handler errors

**Description:** Multiple endpoints return `[]` when handler results are not lists, with only a warning log. The REST API client receives an empty success response with no indication of failure.

```python
if isinstance(result, list):
    return result
logger.warning("list_sessions returned non-list result: %s", type(result).__name__)
return []  # Client can't distinguish "no items" from "handler error"
```

**Impact:** Handler bugs are silently converted to empty success responses. Debugging becomes difficult.

**Suggested fix:** Raise HTTP exceptions for proper error semantics:
```python
if isinstance(result, list):
    return result
logger.error("list_sessions returned non-list result: %s", type(result).__name__)
raise HTTPException(status_code=500, detail="Internal error: unexpected handler result type")
```

### 3. [errors] `rest_adapter.py:140-141,146-148` - HTTP 200 returned for error conditions

**Description:** The `end_session` endpoint returns HTTP 200 with an error body instead of proper HTTP error codes:
- Missing MCP server returns `{"status": "error", ...}` with HTTP 200
- Caught exceptions return `{"status": "error", ...}` with HTTP 200

**Impact:** Clients checking only HTTP status codes will think operations succeeded when they failed.

**Suggested fix:** Use proper HTTP status codes:
```python
if not self.mcp_server:
    raise HTTPException(status_code=503, detail="MCP server not available")

except Exception as e:
    logger.error("Failed to end session %s on %s: %s", session_id, computer, e, exc_info=True)
    raise HTTPException(status_code=500, detail=f"Failed to end session: {e}") from e
```

### 4. [types] `rest_models.py:12-13` - Loose string types for enumerated values

**Description:** `agent` and `thinking_mode` are typed as `str`, allowing any value. The domain only has specific valid values.

**Impact:** Invalid values like `agent="gpt-4"` would be accepted by the API.

**Suggested fix:**
```python
from typing import Literal

agent: Literal["claude", "gemini", "codex"] = "claude"
thinking_mode: Literal["fast", "med", "slow"] = "slow"
```

### 5. [types] `rest_adapter.py:31` - EndSessionResult.status allows illegal states

**Description:** `status: str` permits any string value, but only "success" or "error" are valid.

**Suggested fix:**
```python
class EndSessionResult(TypedDict):
    status: Literal["success", "error"]
    message: str
```

### 6. [code] `rest_adapter.py:257-260` - Synchronous file I/O in async handler

**Description:** The `list_todos` endpoint uses synchronous `Path.read_text()` and `Path.exists()` calls inside an async handler, blocking the event loop.

**Suggested fix:** Use `asyncio.to_thread()`:
```python
import asyncio
content = await asyncio.to_thread(roadmap_path.read_text)
```

### 7. [tests] Missing error path tests for REST adapter

**Description:** REST adapter tests cover mostly happy paths. Missing tests for:
- `end_session` when MCP throws an exception
- `create_session` when `handle_event` returns an error
- `send_message` when `handle_event` fails

## Suggestions (nice to have)

### 8. [code] `rest_adapter.py:301` - Hardcoded socket path

The socket path `/tmp/teleclaude-api.sock` should use a configurable constant like `MCP_SOCKET_PATH`.

### 9. [types] `rest_models.py:20` - No minimum length on message

An empty string `""` would be accepted. Consider:
```python
from pydantic import Field
message: str = Field(..., min_length=1)
```

### 10. [types] `rest_adapter.py:28-32` - Duplicate EndSessionResult definition

`EndSessionResult` is also defined in `teleclaude/mcp/types.py`. Consider importing from there to avoid duplication.

## Strengths

1. **Clean architectural separation** - RESTAdapter properly routes through AdapterClient's event system
2. **Correct adapter key change** - `ADAPTER_KEY = "rest"` properly set
3. **MCP server wiring** - Daemon correctly wires MCP server for end_session operation
4. **MCPServerProtocol type** - Good improvement over previous `object` typing
5. **terminal_sessions.py updated** - Now uses `origin_adapter = 'rest'`
6. **All test files updated** - Consistent `origin_adapter='rest'` across 10+ test files
7. **Good test coverage** - 646 tests passing, comprehensive adapter client tests
8. **Socket lifecycle management** - REST adapter cleans up old sockets on start
9. **Previous review issues fixed** - Column index bug, error logging, unused models removed

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first

### Priority fixes:

1. **CRITICAL - BUG:** Move `CreateSessionRequest`/`SendMessageRequest` imports to module level to fix FastAPI body detection (4 test failures)
2. **IMPORTANT:** Replace silent `return []` fallbacks with HTTP exceptions
3. **IMPORTANT:** Use proper HTTP error codes instead of 200 with error bodies
4. **IMPORTANT:** Add `Literal` types for `agent`, `thinking_mode`, `status` fields
5. **IMPORTANT:** Wrap synchronous file I/O in `asyncio.to_thread()`

---

## Previous Review Fixes (from first review)

| Issue | Fix | Commit |
|-------|-----|--------|
| terminal_sessions.py:82 - wrong column index | Changed row[2] to row[1] for existing_title | bea06ca |
| RESTAdapter has NO unit tests | Created tests/unit/test_rest_adapter.py (17/21 passing) | ac2bf9d |
| Silent empty list returns | Added warning logs for non-list handler results | 95a6830 |
| No error handling for MCP server calls | Wrapped MCP call in try-catch with logging | 1bc286b |
| Silent exception in adapter_client.py | Added debug logging for best-effort deletion failures | 9b3a070 |
| Test files inconsistent with origin_adapter rename | Updated 10 test files from 'terminal' to 'rest' | d674279 |
| Unused response models | Deleted 5 unused model classes | 7e673d3 |
| mcp_server typed as object | Added MCPServerProtocol with proper TypedDict | fdb4a1b |

### Current Test Results

- **646 unit tests passing**
- **4 REST adapter tests failing** (root cause: forward reference annotation issue)
- **Lint: passing** (0 errors)
- **Type check: passing** (0 errors)
