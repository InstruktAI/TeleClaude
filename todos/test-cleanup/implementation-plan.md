# Implementation Plan: Test Cleanup

## Objective

Two goals:
1. **Add missing test coverage** for recent features that have zero tests
2. **Refactor existing tests** to verify observable behavior, not implementation details

The test suite should give confidence that the code works, with clear documentation explaining what each test validates.

## Guiding Principles

**These principles guide ALL decisions during implementation:**

1. **Production code is sacrosanct** - Never modify non-test code. If a test can't be fixed without changing production code, document it and move on.

2. **Behavior over implementation** - Tests should answer "does it work?" not "how does it work internally?"

3. **System boundaries are special** - Mock verification IS acceptable when testing interfaces with external systems (tmux, APIs, file systems). Document why.

4. **Use judgment** - This plan provides direction, not a rigid script. If you encounter situations not covered here, apply the principles and proceed sensibly.

5. **Don't break working tests** - If refactoring a test would require significant changes that risk introducing bugs, document the issue and preserve the working test.

## What to Fix

### Mock Assertion Anti-Patterns

**Replace these patterns:**
```python
# BAD: Verifying internal calls
mock_handler.assert_called_once()
assert mock_send.call_args[0][0] == "expected"
assert mock_db.update.call_count == 2
```

**With outcome-based assertions:**
```python
# GOOD: Verifying observable results
assert result["status"] == "success"
assert session.title == "Expected Title"
assert len(sessions) == 2
```

**Exception - System Boundaries:**
```python
# ACCEPTABLE: External system interface verification
# System boundary: verify correct tmux command construction
mock_exec.assert_called_once()
call_args = mock_exec.call_args[0]
assert call_args == ("tmux", "send-keys", "-t", "session", "text")
```

### Missing Docstrings

Every test function needs a docstring explaining:
- What behavior is being tested
- Under what conditions

**Pattern:** `"""Test that <function/component> <does what> when <condition>."""`

**Examples:**
```python
def test_create_session_returns_session_id():
    """Test that create_session returns a valid session_id on success."""

def test_send_keys_escapes_exclamation_for_gemini():
    """Test that send_keys escapes ! characters when active_agent is gemini."""

def test_cleanup_skips_recently_active_sessions():
    """Test that sessions active within 72 hours are not cleaned up."""
```

## Files to Process

Process in this order (highest impact first). For each file:
1. Read and understand current tests (or production code if adding new tests)
2. Identify violations or missing coverage
3. Add tests / refactor / document as needed
4. Run `make lint` and `make test-unit` (or appropriate test command)
5. Commit when file is complete

### Priority 0: New Tests for Untested Code

These components have **zero test coverage** and need tests written from scratch:

| Component | File to Create | What to Test |
|-----------|----------------|--------------|
| **TmuxPaneManager** | `tests/unit/test_pane_manager.py` | `show_session()`, `hide_sessions()`, `toggle_session()`, `cleanup()`, pane state tracking, behavior when not in tmux |
| **SessionsView activity tracking** | `tests/unit/test_sessions_view.py` | `_update_activity_state()` with idle threshold (60s), state changes (input→output→idle), timezone handling |
| **SessionsView pane toggling** | (same file) | `_toggle_session_pane()` behavior, child session lookup via `initiator_session_id` |
| **PreparationView session launch** | `tests/unit/test_preparation_view.py` | `_launch_session_split()` creates session and splits tmux, curses state save/restore |
| **MCP _extract_tmux_session_name** | `tests/unit/test_mcp_handlers.py` | Helper extracts `tmux_session_name` from result dict, handles missing/malformed data |
| **DB create_session with initiator_session_id** | `tests/unit/test_db.py` (extend) | Verify `initiator_session_id` is stored and retrieved correctly |

**Testing approach for TUI components:**
- Mock `subprocess.run` for tmux commands (system boundary)
- Mock `curses` for screen operations
- Test the logic, not the curses rendering
- Verify correct tmux command construction (acceptable mock verification for system boundary)

**Example test structure for TmuxPaneManager:**
```python
def test_toggle_session_shows_pane_when_none_active():
    """Test that toggle_session creates pane when no session is currently shown."""
    with patch.object(manager, "_run_tmux") as mock_tmux:
        mock_tmux.return_value = "%5"  # pane ID
        result = manager.toggle_session("tc_session_123")
        assert result is True
        assert manager.active_session == "tc_session_123"
        # System boundary: verify tmux split-window command
        mock_tmux.assert_called()
        assert "split-window" in str(mock_tmux.call_args_list)

def test_toggle_session_hides_pane_when_same_session():
    """Test that toggle_session hides pane when toggling same session."""
    manager.state.parent_session = "tc_session_123"
    result = manager.toggle_session("tc_session_123")
    assert result is False
    assert manager.active_session is None
```

### Priority 1: Major Refactoring Required

| File | Mock Violations | Issue Summary |
|------|-----------------|---------------|
| `tests/unit/test_command_handlers.py` | 38 | Heavy mock call verification instead of outcome testing |
| `tests/unit/test_terminal_bridge.py` | 29 | System boundary - keep mock verification but document why |
| `tests/unit/test_mcp_server.py` | 29 | Verifies internal routing instead of MCP tool outcomes |
| `tests/unit/test_daemon.py` | 18 | Mixed - some good, some implementation-detail tests |
| `tests/unit/test_output_poller.py` | 18 | Uses `assert_not_called()` patterns |
| `tests/unit/test_voice_message_handler.py` | 18 | Mixed outcome and mock verification |
| `tests/unit/test_ui_adapter.py` | 16 | Heavy mock call verification |
| `tests/integration/test_mcp_tools.py` | 16 | Verifies call_args on mocked adapters |
| `tests/unit/test_adapter_client.py` | 15 | Mixed - some good peer discovery tests |
| `tests/unit/test_session_cleanup.py` | 10 | Good structure, some mock assertions to fix |

**Progress**
- [x] Refactor `tests/unit/test_command_handlers.py` to assert outcomes via DB state or returned payloads
- [x] Document terminal bridge system-boundary assertions in `tests/unit/test_terminal_bridge.py`
- [x] Reduce internal routing assertions in `tests/unit/test_mcp_server.py`
- [x] Convert daemon tests to capture outcome payloads in `tests/unit/test_daemon.py`
- [x] Paranoidize output poller tests in `tests/unit/test_output_poller.py`
- [x] Paranoidize voice handler tests in `tests/unit/test_voice_message_handler.py`
- [x] Paranoidize UI adapter tests in `tests/unit/test_ui_adapter.py`
- [x] Paranoidize MCP wrapper tests in `tests/unit/test_mcp_wrapper.py`
- [x] Paranoidize session cleanup tests in `tests/unit/test_session_cleanup.py`
- [x] Paranoidize adapter client tests in `tests/unit/test_adapter_client.py`
- [x] Paranoidize MCP tool integration tests in `tests/integration/test_mcp_tools.py`
- [x] Paranoidize set_dependencies tests in `tests/unit/test_mcp_set_dependencies.py`
- [x] Add docstrings in `tests/unit/test_next_machine_hitl.py`
- [x] Add docstrings in `tests/unit/test_agents.py`
- [x] Add docstrings in `tests/unit/test_telegram_adapter.py`
- [x] Add docstrings in `tests/unit/test_hook_receiver.py`
- [x] Add docstrings in `tests/unit/test_terminal_sessions.py`
- [x] Review mock assertions in `tests/unit/test_computer_registry.py`
- [x] Review mock assertions in `tests/integration/test_feedback_cleanup.py`
- [x] Tighten docstrings in `tests/unit/test_voice_assignment.py`
- [x] Add docstrings in `tests/unit/test_agent_parsers.py`
- [x] Add docstrings in `tests/unit/test_terminal_io.py`
- [x] Add docstrings in `tests/unit/test_next_machine_git_env.py`
- [x] Add docstrings in `tests/unit/test_hook_receiver_tty.py`
- [x] Add docstrings in `tests/unit/test_adapter_client_terminal_origin.py`
- [x] Add docstrings in `tests/unit/test_launch_env.py`
- [x] Add docstrings in `tests/unit/test_terminal_events.py`
- [x] Add docstrings in `tests/unit/test_session_watcher_codex.py`
- [x] Add docstrings in `tests/unit/test_mcp_wrapper_tool_refresh.py`
- [x] Add docstrings in `tests/unit/test_config_working_dir.py`

### Priority 2: Docstrings + Minor Fixes

| File | Missing Docstrings | Notes |
|------|-------------------|-------|
| `tests/unit/test_mcp_wrapper.py` | 19/19 | Good tests, just need docstrings |
| `tests/unit/test_mcp_set_dependencies.py` | 12/12 | Add docstrings |
| `tests/unit/test_voice_assignment.py` | 10/10 | Add docstrings |
| `tests/unit/test_next_machine_hitl.py` | 8/20 | Add missing docstrings |
| `tests/unit/test_agents.py` | 6/9 | Add missing docstrings |
| `tests/unit/test_telegram_adapter.py` | 3/18 | Add missing docstrings, review mock usage |
| `tests/unit/test_hook_receiver.py` | 3/6 | Add missing docstrings |
| `tests/unit/test_terminal_sessions.py` | 3/3 | Add docstrings |
| `tests/unit/test_computer_registry.py` | - | Review 6 mock assertions |
| `tests/integration/test_feedback_cleanup.py` | - | Review 5 mock assertions |

### Priority 3: Quick Wins (docstrings only)

These files have 1-2 tests missing docstrings each. Fix them as you encounter them or in a single pass:

- `test_agent_parsers.py`, `test_terminal_io.py`, `test_next_machine_git_env.py`
- `test_hook_receiver_tty.py`, `test_adapter_client_terminal_origin.py`
- `test_launch_env.py`, `test_terminal_events.py`, `test_session_watcher_codex.py`
- `test_mcp_wrapper_tool_refresh.py`, `test_config_working_dir.py`
- `test_ui_adapter_command_overrides.py`, `test_daemon_poller_watch.py`
- `test_terminal_delivery.py`, `test_terminal_io_bracketed_paste.py`

## Verification

After each file:
```bash
make lint                    # Must pass
make test-unit              # Must pass (or targeted: uv run pytest tests/unit/test_<file>.py -v)
```

After all files:
```bash
make test                   # Full suite must pass
```

## Commit Strategy

- Commit after each file or logical group of files
- Use format: `test(<scope>): <description>`
- Examples:
  - `test(command_handlers): refactor to verify outcomes instead of mock calls`
  - `test(mcp_wrapper): add docstrings to all test functions`
  - `test(cleanup): add missing docstrings to minor test files`

## Out of Scope

- **Production code changes** - Tests only
- **Integration test conftest.py refactoring** - Complex but functional, leave as-is
- **Changing test structure/organization** - Just fix quality issues

## Decision Log

Document any significant decisions made during implementation:

| Decision | Rationale |
|----------|-----------|
| Keep mock verification in `test_terminal_bridge.py` | System boundary - testing tmux command construction |
| (add as needed) | |

## Completion Criteria

- [x] All Priority 0 components have new test files with coverage
- [ ] All Priority 1 files refactored
- [ ] All Priority 2 files have docstrings + fixes
- [ ] All Priority 3 files have docstrings
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] Test coverage increased (not decreased)
