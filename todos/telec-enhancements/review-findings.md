# Code Review: telec-enhancements

**Reviewed**: 2026-01-09
**Reviewer**: Claude Opus 4.5 (code-reviewer agent)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| FR-1: REST API Communication (Unix socket) | ✅ | Implemented via FastAPI + uvicorn on `/tmp/teleclaude-api.sock` |
| FR-2: Session Attachment | ⚠️ | Local tmux attachment in telec.py, remote SSH attachment not implemented |
| FR-3: Agent Availability | ✅ | Footer displays availability, modal skips unavailable agents |
| FR-4: Todo Parsing | ✅ | Parses `todos/roadmap.md` correctly with status markers |
| FR-5: External Tool Launch | ✅ | `curses.endwin()` + subprocess + `curses.doupdate()` pattern |
| FR-6: CLI Shortcuts | ⚠️ | `/list`, `/claude`, `/gemini`, `/codex` work; `/agent` and `/agent_resume` removed |
| Sessions View | ✅ | Project-centric tree with AI-to-AI nesting |
| Preparation View | ✅ | Todo-centric view with status and file existence |
| View Switching (1/2 keys) | ✅ | Implemented in TelecApp |
| Start Session Modal | ✅ | Agent/mode selection with unavailable agent handling |
| Color Coding | ⚠️ | Colors defined but not fully applied (placeholders) |
| Action Bar [m] Message | ❌ | Documented but not implemented |
| Action Bar [t] Transcript | ❌ | Documented but not implemented |

## Critical Issues (must fix)

### 1. [lint] `teleclaude/cli/tui/views/sessions.py:185-186` - Unused variables

**Confidence: 95**

```python
colors = AGENT_COLORS.get(agent, {"bright": 7, "muted": 7})
has_output = bool(session.get("last_output"))
```

Variables are assigned but never used. This indicates incomplete implementation of color-coded session rendering.

**Suggested fix**: Either implement color rendering using curses color pairs or remove the unused variables. The requirements specify color coding should indicate session state.

### 2. [types] `teleclaude/api/routes.py:181-182` - Type mismatch in AgentAvailability

**Confidence: 92**

```python
unavailable_until=info.get("unavailable_until"),  # Can be bool | str | None
reason=info.get("reason"),                         # Can be bool | str | None
```

The model expects `str | None` but `dict.get()` from an untyped dict can return any type.

**Suggested fix**:
```python
unavailable_until_raw = info.get("unavailable_until")
unavailable_until = str(unavailable_until_raw) if unavailable_until_raw else None
```

### 3. [tests] No unit tests for new TUI or API code

**Confidence: 100**

The implementation plan specified:
- `tests/unit/test_api_routes.py`
- `tests/unit/test_api_client.py`
- `tests/unit/test_tui_tree.py`
- `tests/unit/test_tui_modal.py`
- `tests/unit/test_tui_todos.py`
- `tests/unit/test_tui_views.py`

None of these exist. The new code has zero test coverage.

**Suggested fix**: Write unit tests for:
1. `build_tree()` function with AI-to-AI nesting
2. `parse_roadmap()` function with various input formats
3. API client methods (mocked HTTP)
4. Modal navigation and agent availability logic

## Important Issues (should fix)

### 4. [code] `teleclaude/cli/tui/views/sessions.py:106` - Empty `_refresh_data` method

**Confidence: 88**

```python
async def _refresh_data(self) -> None:
    """Refresh data from API."""
    # This would be called from main app to refresh all data
    pass
```

Called after session creation but does nothing. Users won't see the new session in the tree.

**Suggested fix**: Either call parent app's `refresh_data()` method or remove the method and let the caller handle refresh.

### 5. [code] `teleclaude/cli/tui/views/sessions.py:113-125` - Empty key handlers

**Confidence: 85**

```python
def handle_key(self, key: int, stdscr: object) -> None:
    if key == ord("n"):
        # New session modal
        pass
    elif key == ord("k"):
        # Kill session
        pass
```

Action bar shows `[n] New  [k] Kill` but handlers are empty stubs.

**Suggested fix**: Implement the handlers or remove them from the action bar to avoid user confusion.

### 6. [code] `teleclaude/cli/telec.py:116` - Accessing private attribute

**Confidence: 82**

```python
if api._client:  # Only close if not already closed
    await api.close()
```

Accessing `_client` directly violates encapsulation. This can break if internal implementation changes.

**Suggested fix**: Add an `is_connected` property or handle double-close gracefully inside `close()`.

### 7. [types] `teleclaude/api/models.py` - Pydantic models use implicit `Any`

**Confidence: 80**

The guardrails detected 42 loose dict typings. Many Pydantic model fields use generic types like `dict[str, object]` where stricter types would improve safety.

**Suggested fix**: Define specific typed models or use TypedDict for nested structures.

### 8. [error] `teleclaude/cli/api_client.py` - HTTP errors not handled gracefully

**Confidence: 80**

All API methods call `resp.raise_for_status()` which raises `httpx.HTTPStatusError`. If daemon is down or API returns error, users see raw exceptions instead of helpful messages.

**Suggested fix**: Wrap in try/except and provide user-friendly error messages or fallback behavior.

## Suggestions (nice to have)

### 9. [code] `teleclaude/cli/tui/app.py:102,119` - Deprecated `get_event_loop()` usage

**Confidence: 70**

```python
asyncio.get_event_loop().run_until_complete(self.refresh_data())
```

`get_event_loop()` is deprecated in Python 3.10+. Should use `asyncio.run()` or better integration with curses.

**Suggested fix**: Consider using `asyncio.run()` or the `async_curses` pattern for cleaner async integration.

### 10. [simplify] Modal and views use `object` type for `stdscr`

**Confidence: 65**

Using `stdscr: object` loses type safety. Could use `curses.window` or define a protocol.

**Suggested fix**: Use proper curses typing: `stdscr: "curses.window"` with appropriate import.

### 11. [code] Session matching uses `working_directory` instead of `project_dir`

**Confidence: 75**

In `tree.py:71`:
```python
if s.get("computer") == comp_name and s.get("working_directory") == proj_path
```

The requirements document mentions `project_dir` field, but code uses `working_directory`. Verify these are equivalent.

## Strengths

- Clean module structure following the implementation plan
- Good separation of concerns: API routes, client, TUI views, widgets
- AI-to-AI session nesting logic is well-designed in `tree.py`
- Todo parsing handles all status markers correctly
- Modal properly skips unavailable agents

## Verdict

**[x] REQUEST CHANGES** - Fix critical/important issues first

### Priority fixes:

1. Add unit tests for `parse_roadmap()`, `build_tree()`, and API client methods
2. Fix unused variables in sessions view or complete color implementation
3. Fix type errors in `routes.py:181-182`
4. Implement or remove empty handler stubs
5. Fix private attribute access in telec.py
6. Add error handling for API client failures
