# Testing Refactor Plan

## Progress

**Phase 1: COMPLETE** ✅✅✅
- Deleted 19 manual test files (manual scripts + API scripts + useless tests)
- Fixed all broken imports after refactoring:
  - test_core.py: TerminalBridge → terminal_bridge
  - test_voice_status_append.py: OutputMessageManager → output_message_manager
  - test_full_flow.py: daemon.terminal → terminal_bridge
  - conftest.py: Added terminal_bridge import and cleanup
- Fixed integration test fixture issues:
  - Config reset before each test (prevent "already initialized" errors)
  - Database cleanup at start of fixture (prevent session accumulation)
  - terminal_bridge module usage in cleanup
- **All 138 tests passing in 3.31s** (no manual waiting!)
- **137 passing tests** (130 unit + 7 integration)

## Summary

We have **massive coverage gaps** in unit tests for our newly refactored modules, and integration tests that duplicate unit test coverage or are broken.

**Problems:**
- 9 core modules have NO unit tests (0% coverage)
- 8 integration tests have broken imports (non-existent classes)
- 4 manual scripts disguised as tests (should be deleted)
- 2 API scripts in test directory (should be deleted)
- Integration tests duplicate unit test coverage

**Goal:**
- >90% code coverage via comprehensive unit tests
- Clean integration tests testing real component integration (no duplication)
- Fast test suite (unit tests fast, integration tests focused)

---

## Phase 1: Clean Up Integration Tests

### 1.1 DELETE Manual Test Scripts

**These are NOT proper pytest tests - they are manual scripts with inline logic duplication:**

```bash
rm tests/integration/test_cancel_daemon.py
rm tests/integration/test_cancel_output.py
rm tests/integration/test_output_polling.py
rm tests/integration/test_polling.py
```

**Rationale:**
- Use `if __name__ == "__main__"` instead of pytest framework
- Duplicate polling logic inline instead of testing through proper APIs
- Should be unit tests instead (will create proper tests in Phase 2)

### 1.2 DELETE API Scripts

**These are NOT tests - they send real Telegram API requests:**

```bash
rm tests/integration/test_cd.py
rm tests/integration/test_message.py
```

**Rationale:**
- Not automated tests, just manual API interaction scripts
- Proper tests will be created in Phase 4 (if needed)

### 1.3 Fix Remaining Integration Tests

**Files with broken imports (importing deleted classes):**

1. **test_core.py** - Fix TerminalBridge import:
   ```python
   # BEFORE
   from teleclaude.core.terminal_bridge import TerminalBridge
   terminal = TerminalBridge()
   await terminal.create_tmux_session(...)

   # AFTER
   from teleclaude.core import terminal_bridge
   await terminal_bridge.create_tmux_session(...)
   ```

2. **test_voice_status_append.py** - Fix OutputMessageManager import:
   ```python
   # BEFORE
   from teleclaude.core.output_message_manager import OutputMessageManager
   manager = OutputMessageManager()
   await manager.send_status_message(...)

   # AFTER
   from teleclaude.core import output_message_manager
   await output_message_manager.send_status_message(...)
   ```

3. **test_full_flow.py** - Verify imports are correct (likely needs fixing)

4. **test_process_exit_detection.py** - Verify imports are correct

**Manual test files (tests/manual/) - Fix if used, or delete:**
- `test_tmux_responsiveness.py` - Fix TerminalBridge import
- `test_voice_transcription.py` - Fix VoiceHandler import
- `monitor_responsiveness.py` - Fix TerminalBridge import
- `test_emulate_messages.py` - Fix TerminalBridge import

**Verification:**
```bash
make test  # Should pass without import errors
```

---

## Phase 2: Add Missing Unit Tests (HIGH PRIORITY)

### Coverage Gaps - 9 Core Modules with NO Unit Tests

**Priority 1: Core Logic (Message Flow)**

#### 2.1 Create `tests/unit/test_output_message_manager.py`

**Module:** `teleclaude/core/output_message_manager.py`

**Tests to create:**
- `test_format_output_message()` - Message formatting with code blocks
- `test_format_output_message_truncation()` - Truncation to 3400 chars
- `test_generate_status_line()` - Status line generation (time, size, truncated indicator)
- `test_send_output_update()` - Output update logic (edit vs new message)
- `test_send_status_message()` - Status message sending
- `test_send_exit_message()` - Exit message formatting
- `test_append_to_existing()` - Appending to existing output

**Mocking strategy:**
- Mock adapter.send_message(), adapter.edit_message()
- Mock session_manager.get_output_message_id()
- Use real file I/O with temp files

#### 2.2 Create `tests/unit/test_state_manager.py`

**Module:** `teleclaude/core/state_manager.py`

**Tests to create:**
- `test_is_polling()` - Check polling state
- `test_mark_polling()` - Set polling active
- `test_unmark_polling()` - Clear polling state
- `test_set_exit_marker()` - Store exit marker flag
- `test_get_exit_marker()` - Retrieve exit marker flag
- `test_remove_exit_marker()` - Clear exit marker
- `test_add_idle_notification()` - Store idle notification message ID
- `test_has_idle_notification()` - Check if notification exists
- `test_remove_idle_notification()` - Clear notification

**Mocking strategy:**
- NO mocking needed - pure module-level state management
- Test state isolation between tests

#### 2.3 Create `tests/unit/test_message_handler.py`

**Module:** `teleclaude/core/message_handler.py`

**Tests to create:**
- `test_handle_message_new_command()` - New command with exit marker
- `test_handle_message_running_process()` - Input to running process (no exit marker)
- `test_double_slash_stripping()` - // at start → /
- `test_double_slash_not_stripped_middle()` - // in middle preserved
- `test_delete_user_message_when_polling()` - Message deleted if process running
- `test_delete_idle_notification()` - Idle notification deleted on new input

**Mocking strategy:**
- Mock session_manager methods
- Mock terminal_bridge.send_keys()
- Patch state_manager.is_polling()
- Mock adapter methods

#### 2.4 Create `tests/unit/test_terminal_executor.py`

**Module:** `teleclaude/core/terminal_executor.py`

**Tests to create:**
- `test_execute_terminal_command_success()` - Successful execution
- `test_execute_terminal_command_failure()` - Failed execution
- `test_append_exit_marker_true()` - Exit marker appended
- `test_append_exit_marker_false()` - No exit marker
- `test_start_polling_after_execution()` - Polling started after command
- `test_no_polling_without_exit_marker()` - No polling if exit marker false
- `test_session_not_found()` - Error handling

**Mocking strategy:**
- Mock session_manager.get_session()
- Patch terminal_bridge.send_keys()
- Patch state_manager.set_exit_marker()
- Mock start_polling callback

#### 2.5 Create `tests/unit/test_polling_coordinator.py`

**Module:** `teleclaude/core/polling_coordinator.py`

**Tests to create:**
- `test_poll_and_send_output_flow()` - Full polling flow
- `test_output_changed_event()` - Handle OutputChanged event
- `test_idle_detected_event()` - Handle IdleDetected event
- `test_process_exited_event()` - Handle ProcessExited event
- `test_delete_idle_notification_on_output()` - Idle notification cleanup
- `test_cleanup_on_exit()` - State cleanup in finally block
- `test_duplicate_polling_prevention()` - Guard against duplicate polling

**Mocking strategy:**
- Mock OutputPoller.poll() to yield test events
- Mock output_message_manager functions
- Mock adapter methods
- Mock session_manager methods
- Patch state_manager functions

**Priority 2: Command Handling**

#### 2.6 Create `tests/unit/test_command_handlers.py`

**Module:** `teleclaude/core/command_handlers.py`

**Tests to create:**

**Cancel/Escape commands:**
- `test_handle_cancel_command_single()` - Single SIGINT
- `test_handle_cancel_command_double()` - Double SIGINT
- `test_handle_escape_command_single()` - Single ESC
- `test_handle_escape_command_double()` - Double ESC

**Session management:**
- `test_handle_resize_session()` - Resize terminal
- `test_handle_rename_session()` - Update title
- `test_handle_exit_session()` - Exit and cleanup

**Directory navigation:**
- `test_handle_cd_session_workdir()` - CD to TC WORKDIR
- `test_handle_cd_session_parent()` - CD to parent (..)
- `test_handle_cd_session_absolute()` - CD to absolute path
- `test_handle_cd_session_no_args()` - Show directory selector

**Claude commands:**
- `test_handle_claude_session()` - Start Claude Code
- `test_handle_claude_resume_session()` - Resume Claude Code

**Error handling:**
- `test_session_not_found()` - Missing session handling
- `test_invalid_arguments()` - Argument validation

**Mocking strategy:**
- Mock session_manager.get_session()
- Patch terminal_bridge functions
- Mock adapter methods
- Mock execute_terminal_command callback
- Mock start_polling callback

#### 2.7 Create `tests/unit/test_session_lifecycle.py`

**Module:** `teleclaude/core/session_lifecycle.py`

**Tests to create:**
- `test_create_new_session()` - Create session flow
- `test_create_session_with_metadata()` - With adapter metadata
- `test_close_session()` - Session deletion
- `test_cleanup_on_close()` - Tmux session killed, channel deleted
- `test_close_nonexistent_session()` - Error handling

**Mocking strategy:**
- Mock session_manager methods
- Patch terminal_bridge functions
- Mock adapter methods

#### 2.8 Create `tests/unit/test_event_handlers.py`

**Module:** `teleclaude/core/event_handlers.py`

**Tests to create:**
- `test_route_message_event()` - Route to message_handler
- `test_route_command_event()` - Route to command_handlers
- `test_route_voice_event()` - Route to voice_message_handler
- `test_route_file_event()` - Route to file handler (if exists)
- `test_route_topic_closed_event()` - Route to session cleanup

**Mocking strategy:**
- Mock all handler functions
- Mock session_manager
- Verify correct routing

#### 2.9 Create `tests/unit/test_voice_message_handler.py`

**Module:** `teleclaude/core/voice_message_handler.py`

**Tests to create:**
- `test_handle_voice_success()` - Successful transcription + execution
- `test_handle_voice_no_process_running()` - Reject if no active process
- `test_handle_voice_no_output_message()` - Reject if no output message yet
- `test_handle_voice_transcription_failure()` - Handle transcription failure
- `test_handle_voice_cleanup()` - Audio file cleanup
- `test_handle_voice_session_not_found()` - Error handling

**Mocking strategy:**
- Mock session_manager.get_session()
- Patch state_manager.is_polling()
- Mock transcribe_voice_with_retry()
- Patch terminal_bridge.send_keys()
- Mock adapter methods
- Mock file operations (Path.unlink)

**Priority 3: Expand Existing Unit Tests**

#### 2.10 Expand `tests/unit/test_terminal_bridge.py`

**Add tests for uncovered functions:**
- `test_create_tmux_session()`
- `test_session_exists()`
- `test_capture_pane()`
- `test_send_signal()`
- `test_send_escape()`
- `test_kill_session()`
- `test_list_sessions()`
- `test_resize_session()`

**Current coverage:** ~30% (only send_keys + validation)
**Target:** >90%

#### 2.11 Expand `tests/unit/test_output_poller.py`

**Add tests for uncovered logic:**
- `test_poll_flow()` - Full polling flow (generator)
- `test_output_changed_detection()` - Detect output changes
- `test_idle_detection()` - Detect idle timeout
- `test_exit_code_detection()` - Detect exit marker
- `test_scrubber_position_tracking()` - Track last read position
- `test_chunk_splitting()` - Split large output into chunks

**Current coverage:** ~20% (only extract_exit_code)
**Target:** >90%

---

## Phase 3: Verify Coverage

### 3.1 Run Coverage Analysis

```bash
pytest --cov=teleclaude --cov-report=html --cov-report=term-missing
```

### 3.2 Target Metrics

**Core modules (teleclaude/core/):**
- >90% line coverage
- >85% branch coverage

**Daemon (teleclaude/daemon.py):**
- >90% line coverage

**Adapters (teleclaude/adapters/):**
- >80% line coverage

**Overall project:**
- >85% line coverage

### 3.3 Coverage Report

Open HTML report:
```bash
open coverage/html/index.html
```

Identify gaps:
```bash
pytest --cov=teleclaude --cov-report=term-missing | grep -E "TOTAL|teleclaude"
```

### 3.4 Address Gaps

**For any module <90% coverage:**
1. Review coverage report to find untested lines
2. Add unit tests for missing branches/conditions
3. Re-run coverage to verify

---

## Phase 4: Add Missing Integration Tests (Optional)

**Only proceed if user wants end-to-end command testing beyond unit tests.**

### 4.1 Create `tests/integration/test_cd_command.py`

**Test full /cd flow:**
- Create real tmux session
- Send /cd command with directory path
- Verify tmux working directory changed
- Verify session.working_directory updated in database
- Test directory selector (inline keyboard)

### 4.2 Create `tests/integration/test_rename_command.py`

**Test full /rename flow:**
- Create real session
- Send /rename command
- Verify session.title updated in database
- Verify Telegram topic title updated

### 4.3 Create `tests/integration/test_cancel_command.py`

**Test full /cancel flow:**
- Create real tmux session
- Start long-running process
- Send /cancel command
- Verify SIGINT sent
- Verify output captured
- Verify process stopped

### 4.4 Create `tests/integration/test_escape_command.py`

**Test full /escape flow:**
- Create real tmux session with vim
- Send /escape command
- Verify ESC key sent
- Verify vim responds correctly

---

## Testing Principles

### Unit Tests (Fast, Isolated)

**What:**
- Test logic/behavior through public interfaces
- Mock all I/O (database, tmux, Telegram, file system)
- Use dependency injection (pass dependencies as parameters)
- Test edge cases, error conditions, boundary values

**How:**
- Use AsyncMock for async dependencies
- Use patch() for module-level state
- Use temp files for file I/O when needed
- Test one thing per test

**Target:**
- >90% code coverage
- <1 second total runtime for all unit tests

### Integration Tests (Real Components)

**What:**
- Test real component integration (tmux + database + daemon)
- Mock only external APIs (Telegram, Whisper)
- Test critical user flows end-to-end
- Don't duplicate unit test coverage

**How:**
- Use real tmux sessions (cleanup in teardown)
- Use real temp databases
- Mock Telegram API calls
- Mock Whisper API calls

**Target:**
- Test each major user flow (message execution, voice, commands)
- <10 seconds total runtime
- No duplication of unit test coverage

---

## Execution Order

1. **Phase 1** - Clean up (30 min)
   - Delete manual scripts
   - Delete API scripts
   - Fix broken imports in remaining integration tests
   - Verify `make test` passes

2. **Phase 2** - Unit tests (4-6 hours)
   - Priority 1: Core logic (steps 2.1-2.5)
   - Priority 2: Command handling (steps 2.6-2.9)
   - Priority 3: Expand existing (steps 2.10-2.11)

3. **Phase 3** - Verify coverage (30 min)
   - Run coverage analysis
   - Identify gaps
   - Add missing tests

4. **Phase 4** - Integration tests (2 hours, optional)
   - Only if user wants end-to-end command testing
   - Create integration tests for critical commands

---

## Success Criteria

✅ All tests pass: `make test`
✅ >90% coverage for core modules: `pytest --cov`
✅ No manual test scripts in tests/integration/
✅ No broken imports
✅ Fast test suite (<2 sec unit, <10 sec integration)
✅ No duplication between unit and integration tests

---

## Notes

**DI Pattern (Best Practice):**
- Prefer passing dependencies as function parameters
- Use `Optional[Type] = None` with fallback to module-level state
- This enables both production use (global state) and testing (inject mocks)
- Example from test_voice.py - no patching needed, just inject mock client

**Mocking Strategy:**
- Mock at boundaries (database, tmux, Telegram, file I/O)
- Don't mock the code under test
- Use real objects when possible (data models, pure functions)
- Test behavior, not implementation

**Test Organization:**
- One test file per module
- Group related tests in classes (TestClassName)
- Clear test names: test_what_when_expected()
- Use fixtures for common setup (but don't overuse)
