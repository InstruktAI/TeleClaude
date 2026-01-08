# DB Refactor: Remaining Test Fixes

## Summary

The core refactoring is complete - all application code has been updated to use direct column access instead of SessionUXState/get_ux_state/update_ux_state methods. Integration tests are passing (37 passed, 1 skipped).

**Current test status:** 26 failed unit tests + 2 import errors

## Completed Test Fixes

- ✅ test_adapter_client_terminal_origin.py
- ✅ test_adapter_client.py
- ✅ test_mcp_server.py (removed get_ux_state mocks)
- ✅ tests/integration/test_process_exit_detection.py
- ✅ tests/integration/test_feedback_cleanup.py

## Remaining Test Files Needing Fixes

### Import Errors (Blocking)

1. **test_command_handlers.py**
   - Status: Import statement removed, but ~18 mock usages need updating
   - Pattern: Replace `SessionUXState(thinking_mode="X")` mocks with session objects
   - Pattern: Remove `mock_db.get_ux_state` and `mock_db.update_ux_state` mocks

2. **test_session_watcher_codex.py**
   - Status: Not started
   - Has SessionUXState import and usages

### Test Failures (Non-blocking)

3. **test_ux_state.py** - 7 failures
   - Tests for SessionUXState.from_dict, to_dict, etc.
   - These tests should be DELETED - SessionUXState no longer exists
   - Keep SystemUXState tests only

4. **test_ui_adapter.py** - 2 failures
   - Lines 330, 351: Uses `update_ux_state` for pending_feedback_deletions
   - Replace with `add_pending_feedback_deletion` table method

5. **test_db.py** - 1 failure
   - Line 490: `update_ux_state(session.session_id, output_message_id="msg123")`
   - Replace with `update_session(session.session_id, output_message_id="msg123")`

6. **test_file_handler.py** - 5 failures
   - Lines 200, 236, 272: Mock `db.get_ux_state`
   - Pattern: Remove the mocks (not needed anymore)

7. **test_daemon.py** - 4 failures
   - Lines 189, 231: Mock `get_ux_state` returning `active_agent`
   - Replace with session objects that have active_agent field

8. **test_terminal_sessions.py** - 2 failures
   - Uses ux_state in assertions
   - Update to check session columns directly

9. **test_telec_sessions.py** - 1 failure
   - Parses ux_state JSON
   - Update to work with session columns

10. **test_daemon_startup_retry.py**
    - Lines 139, 182: Mock get_ux_state
    - Remove the mocks

11. **test_daemon_agent_stop_forwarded.py**
    - Line 28: Mock get_ux_state with assertion error
    - Remove the mock

12. **test_polling_coordinator_pending_deletions.py**
    - Lines 39, 83: Mock update_ux_state
    - Remove the mocks (not needed)

## Fix Patterns

### Pattern 1: Remove SessionUXState imports
```python
# Before
from teleclaude.core.ux_state import SessionUXState

# After
# (just delete the import)
```

### Pattern 2: Replace get_ux_state mocks returning simple values
```python
# Before
mock_db.get_ux_state = AsyncMock(return_value=SessionUXState(thinking_mode="slow"))

# After
# Create session with the field directly or remove mock if not needed
```

### Pattern 3: Replace update_ux_state calls in tests
```python
# Before
await test_db.update_ux_state(session.session_id, output_message_id="msg123")

# After
await test_db.update_session(session.session_id, output_message_id="msg123")
```

### Pattern 4: Replace pending_feedback_deletions usage
```python
# Before
await test_db.update_ux_state(session.session_id, pending_feedback_deletions=[msg_id])

# After
await test_db.add_pending_feedback_deletion(session.session_id, msg_id)
```

### Pattern 5: Delete SessionUXState tests entirely
```python
# test_ux_state.py - DELETE these test functions:
# - test_session_ux_state_from_dict_handles_missing_fields
# - test_session_ux_state_to_dict_serializes_all_fields
# - test_get_session_ux_state_*
# - test_update_session_ux_state_*
```

## Estimated Work

- **Time:** 30-45 minutes for all remaining fixes
- **Complexity:** Low - mostly mechanical find/replace
- **Risk:** Low - tests are isolated, won't affect production code

## Next Steps

1. Fix the 2 import errors (test_command_handlers.py, test_session_watcher_codex.py)
2. Delete SessionUXState tests from test_ux_state.py
3. Fix remaining mocks in other test files (pattern-based replacements)
4. Run full test suite to verify all passes
5. Update state.json to mark build as complete with passing tests
